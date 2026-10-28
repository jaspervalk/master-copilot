"""Kaarten maken voor een hele week, onderwerp voor onderwerp.

Het weekoverzicht wijst aan welke onderwerpen uit course.yml nog geen kaart
hebben; dit vult precies die gaten. Een onderwerp waar geen stof voor is, komt
mét reden terug in plaats van dat het model iets verzint.
"""
from app.models import Chunk, Course, Document, PracticeCard
from app.services.study.generation import MIN_CHUNKS_PER_TOPIC, fill_week


REGRESSIE = (
    "The simple linear regression model is Y = beta0 + beta1 x + E. "
    "Least squares estimates minimise the sum of squared errors, and the slope "
    "is estimated by the least squares criterion for linear regression."
)
LOGISTIEK = (
    "Logistic regression models the log-odds of a binary response. "
    "The logistic regression coefficient is interpreted on the log-odds scale."
)


def _course(db, *, week_plans):
    db.add(Course(slug="sso", name="SSO", week_plans=week_plans))
    db.commit()


def _document(db, *, week, texts, title="Lecture 5"):
    document = Document(
        title=title,
        source_path=f"sso/slides/week-{week:02d}/{title.lower().replace(' ', '')}.pdf",
        checksum=f"sha-{title}",
        course_slug="sso",
        doc_kind="slides",
        week=week,
        ingestion_status="indexed",
    )
    for index, text in enumerate(texts):
        document.chunks.append(
            Chunk(
                chunk_index=index,
                section_path=f"{title} › slide {index + 1}",
                page_start=index + 1,
                page_end=index + 1,
                token_count=30,
                text=text,
                normalized_text=text.lower(),
                chunk_metadata={},
            )
        )
    db.add(document)
    db.commit()
    return document


class _FakeClient:
    """Levert per aanroep één kaart en onthoudt met welk onderwerp is gevraagd."""

    def __init__(self):
        self.topics: list[str] = []
        outer = self

        class _Responses:
            def parse(self, *, model, instructions, input, text_format):
                outer.topics.append(input.splitlines()[0])
                draft = text_format.model_fields["cards"].annotation.__args__[0]
                return type(
                    "Parsed",
                    (),
                    {
                        "output_parsed": text_format(
                            cards=[
                                draft(
                                    chunk_id="onbekend",
                                    question="Bij een steekproef van 30 waarnemingen; welke aanpak past?",
                                    options=["Lineaire regressie", "Chi-kwadraattoets", "Tekentoets", "F-toets"],
                                    correct="a",
                                    procedure="Lineaire regressie",
                                    checks=["lineariteit", "constante variantie"],
                                    explanation="Goed: a. Het gaat om een continue uitkomst tegen een continue voorspeller.",
                                    source_quote="least squares estimates minimise the sum of squared errors",
                                )
                            ]
                        )
                    },
                )()

        self.responses = _Responses()


def test_every_topic_with_material_gets_its_own_round(db_session):
    _course(db_session, week_plans={"3": {"lectures": [5], "topics": ["linear regression"], "reading": []}})
    _document(db_session, week=3, texts=[REGRESSIE, REGRESSIE, REGRESSIE])
    client = _FakeClient()

    report = fill_week(db_session, "sso", 3, count=1, client=client)

    assert report.created == 1
    card = db_session.query(PracticeCard).one()
    assert card.week == 3
    assert card.spec["topic"] == "linear regression"
    assert "linear regression" in client.topics[0]


def test_a_topic_without_material_is_named_not_invented(db_session):
    """Het optimalisatiedeel staat in de studiewijzer voordat de slides er zijn.
    Dan hoort er een melding te komen, geen verzonnen kaart."""
    _course(
        db_session,
        week_plans={"3": {"lectures": [5], "topics": ["linear regression", "simulated annealing"], "reading": []}},
    )
    _document(db_session, week=3, texts=[REGRESSIE, REGRESSIE, REGRESSIE])
    client = _FakeClient()

    report = fill_week(db_session, "sso", 3, count=1, client=client)

    assert report.skipped == [("simulated annealing", f"minder dan {MIN_CHUNKS_PER_TOPIC} fragmenten over dit onderwerp")]
    assert len(client.topics) == 1


def test_a_topic_that_already_has_cards_is_left_alone(db_session):
    _course(db_session, week_plans={"3": {"lectures": [5], "topics": ["linear regression"], "reading": []}})
    document = _document(db_session, week=3, texts=[REGRESSIE, REGRESSIE, REGRESSIE])
    db_session.add(
        PracticeCard(
            course_slug="sso", document_id=document.id, chunk_id="c", section_path="Lecture 5",
            page_start=1, page_end=1, kind="mc", setup="", question="bestaat al",
            # Een keuzekaart: `mc` mét procedure. Zonder procedure is het een tentamenvraag.
            reference_answer="x", week=3, spec={"topic": "linear regression", "procedure": "Lineaire regressie"},
        )
    )
    db_session.commit()
    client = _FakeClient()

    report = fill_week(db_session, "sso", 3, count=1, client=client)

    assert report.created == 0
    assert client.topics == []


def test_a_week_without_topics_in_course_yml_says_so(db_session):
    _course(db_session, week_plans={})
    _document(db_session, week=3, texts=[REGRESSIE])

    report = fill_week(db_session, "sso", 3, count=1, client=_FakeClient())

    assert report.created == 0
    assert any("course.yml" in reason for _, reason in report.skipped)


def test_topics_are_matched_on_their_own_words(db_session):
    """Twee onderwerpen, twee soorten stof: elk onderwerp krijgt alleen de
    fragmenten die er echt over gaan."""
    _course(
        db_session,
        week_plans={"4": {"lectures": [7], "topics": ["logistic regression"], "reading": []}},
    )
    _document(db_session, week=4, texts=[LOGISTIEK, LOGISTIEK, REGRESSIE], title="Lecture 7")
    client = _FakeClient()

    fill_week(db_session, "sso", 4, count=1, client=client)

    assert len(client.topics) == 1


def test_exam_cards_made_for_a_week_carry_that_week_and_topic(db_session):
    """Anders sluit het gat in het weekoverzicht nooit: de kaart draagt dan het
    onderwerp dat het model zelf verzon, niet dat uit de studiewijzer."""
    from app.models import PracticeCard
    from app.services.practice.exam_generation import ExamDraft, RubricDraft, build_card

    document = _document(db_session, week=3, texts=[REGRESSIE])
    chunk = document.chunks[0]
    draft = ExamDraft(
        chunk_id=chunk.id,
        kind="open",
        template="explain_concept",
        topic="iets wat het model zelf bedacht",
        question="Leg uit waarom kleinste kwadraten de som van gekwadrateerde fouten minimaliseert.",
        options=[],
        multi=False,
        correct=[],
        compute="",
        model_answer="Omdat de afgeleide naar de parameters nul wordt gezet.",
        rubric=[RubricDraft(criterion="noemt de afgeleide", points=2.0, source_quote="least squares estimates minimise the sum of squared errors")],
        max_items=0,
        points=4.0,
        explanation="De afleiding staat in de slides.",
        source_quote="least squares estimates minimise the sum of squared errors",
    )

    card = build_card(draft, chunk, document, "sso", "Lecture 5", topic="linear regression", week=3)

    assert isinstance(card, PracticeCard)
    assert card.spec["topic"] == "linear regression"
    assert card.week == 3


def test_a_topic_with_choice_cards_can_still_get_code_cards(db_session):
    """Welk model past, en wat print het — twee vaardigheden bij hetzelfde
    onderwerp. Eerst sloeg aanvullen een onderwerp over zodra er één kaart van
    wélke soort ook bij hoorde, en kreeg 'simulation' na de keuzekaarten nooit
    meer een codevraag."""
    from app.services.study.generation import _topics_with_cards

    _course(db_session, week_plans={"7": {"lectures": [12], "topics": ["simulation"], "reading": []}})
    document = _document(db_session, week=7, texts=[REGRESSIE])
    db_session.add(
        PracticeCard(
            course_slug="sso", document_id=document.id, chunk_id="c", section_path="Lecture 12",
            page_start=1, page_end=1, kind="mc", setup="", question="welk model?",
            reference_answer="x", week=7, spec={"topic": "simulation", "procedure": "Monte Carlo"},
        )
    )
    db_session.commit()

    assert _topics_with_cards(db_session, "sso", 7, kind="keuze") == {"simulation"}
    assert _topics_with_cards(db_session, "sso", 7, kind="output") == set()


def test_exam_cards_and_choice_cards_are_told_apart(db_session):
    """Allebei `mc`; een keuzekaart draagt een procedure, een tentamenvraag niet."""
    from app.services.study.generation import _topics_with_cards

    _course(db_session, week_plans={"3": {"lectures": [5], "topics": ["regression"], "reading": []}})
    document = _document(db_session, week=3, texts=[REGRESSIE])
    db_session.add(
        PracticeCard(
            course_slug="sso", document_id=document.id, chunk_id="c", section_path="Lecture 5",
            page_start=1, page_end=1, kind="mc", setup="", question="tentamenvraag",
            reference_answer="a", week=3, spec={"topic": "regression"},
        )
    )
    db_session.commit()

    assert _topics_with_cards(db_session, "sso", 3, kind="exam") == {"regression"}
    assert _topics_with_cards(db_session, "sso", 3, kind="keuze") == set()


def test_a_week_gets_at_most_one_output_card_per_topic(db_session, monkeypatch):
    """In SSO week 5 waren twaalf van de twintig kaarten 'wat print dit': elke
    soort kreeg evenveel kaarten per onderwerp. Code lezen is één vaardigheid
    naast welk model past en hoe je rekent; één fragment per onderwerp is genoeg."""
    from app.services.study import generation

    gevraagd = []

    def nep_generate_cards(db, *, count, kind, **_):
        gevraagd.append((kind, count))
        return type("Ronde", (), {"created": [], "rejected": []})()

    monkeypatch.setattr(generation, "generate_cards", nep_generate_cards)
    _course(db_session, week_plans={"3": {"lectures": [5], "topics": ["linear regression"], "reading": []}})
    _document(db_session, week=3, texts=[REGRESSIE, REGRESSIE, REGRESSIE])

    fill_week(db_session, "sso", 3, kind="output", count=4, client=object())
    fill_week(db_session, "sso", 3, kind="keuze", count=4, client=object())

    assert gevraagd == [("output", 1), ("keuze", 4)]
