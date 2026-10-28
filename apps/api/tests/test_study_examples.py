"""Uitgewerkte voorbeelden per onderwerp, met een figuur die echt getekend is.

Gekeurd zoals de rest: stappen die er zijn, een citaat dat letterlijk in je
stof staat, en een figuur die het ook doet. Een voorbeeld waarvan de figuur
niet tekent, blijft bestaan zónder figuur — het plaatje is de bonus, de
uitwerking is de kern.
"""
from app.models import Chunk, Course, Document, Example
from app.services.study.examples import ExampleDraft, check_example_draft, make_examples


REGRESSIE = (
    "The simple linear regression model is Y = beta0 + beta1 x + E. "
    "Least squares estimates minimise the sum of squared errors for linear regression. "
    "The residual standard error measures the spread around the fitted line."
)


def _course(db, *, week_plans=None, study=None):
    db.add(Course(slug="sso", name="SSO", week_plans=week_plans or {}, study=study or {}))
    db.commit()


def _document(db, *, week=3, texts=(REGRESSIE, REGRESSIE, REGRESSIE)):
    document = Document(
        title="Lecture 5",
        source_path=f"sso/slides/week-{week:02d}/lecture5.pdf",
        checksum=f"sha-{week}",
        course_slug="sso",
        doc_kind="slides",
        week=week,
        ingestion_status="indexed",
    )
    for index, text in enumerate(texts):
        document.chunks.append(
            Chunk(
                chunk_index=index, section_path=f"Lecture 5 › slide {index}", page_start=index + 1,
                page_end=index + 1, token_count=30, text=text, normalized_text=text.lower(), chunk_metadata={},
            )
        )
    db.add(document)
    db.commit()
    return document


def _draft(**overrides):
    velden = dict(
        chunk_id="onbekend",
        title="Een helling schatten en aflezen",
        situation="Bij 20 steden is het gemiddelde inkomen tegen de afstand tot het centrum gemeten.",
        steps=[
            {"label": "Model", "body": "We schrijven $Y = \\beta_0 + \\beta_1 x + E$."},
            {"label": "Schatten", "body": "Kleinste kwadraten minimaliseert $\\sum (y_i - \\hat y_i)^2$."},
            {"label": "Aflezen", "body": "De helling $\\hat\\beta_1 = -0.8$ betekent 0,8 minder per kilometer."},
        ],
        takeaway="De helling is het verschil in de respons per eenheid van de voorspeller.",
        prompt="Waarom verandert de helling niet als je de eenheid van de respons in duizenden uitdrukt?",
        source_quote="least squares estimates minimise the sum of squared errors",
        figure_code="",
        figure_caption="",
    )
    velden.update(overrides)
    return ExampleDraft(**velden)


class _FakeClient:
    def __init__(self, drafts):
        self._drafts = drafts
        self.prompts: list[str] = []
        self.instructions: list[str] = []
        outer = self

        class _Responses:
            def parse(self, *, model, instructions, input, text_format):
                outer.prompts.append(input)
                outer.instructions.append(instructions)
                return type("Parsed", (), {"output_parsed": text_format(examples=outer._drafts)})()

        self.responses = _Responses()


def test_a_good_draft_becomes_an_example(db_session):
    _course(db_session, week_plans={"3": {"lectures": [5], "topics": ["linear regression"], "reading": []}})
    _document(db_session)

    report = make_examples(db_session, "sso", 3, client=_FakeClient([_draft()]), figures=False)

    assert report.created == 1
    example = db_session.query(Example).one()
    assert example.week == 3
    assert example.topic == "linear regression"
    assert len(example.steps) == 3
    assert example.prompt.endswith("?")
    assert example.figure_svg == ""


def test_the_examples_are_written_for_what_the_course_assesses(db_session):
    """AFCS heeft geen tentamen statistiek maar quizzen over de slides. Een
    voorbeeld voor het verkeerde soort toets oefent het verkeerde."""
    _course(
        db_session,
        week_plans={"3": {"lectures": [5], "topics": ["linear regression"], "reading": []}},
        study={"code": "none", "assessment": "vijf quizzen over de slides"},
    )
    _document(db_session)
    client = _FakeClient([_draft()])

    make_examples(db_session, "sso", 3, client=client, figures=False)

    assert "vijf quizzen over de slides" in client.instructions[0]
    assert "statistiek voorbereidt" not in client.instructions[0]


def test_without_an_assessment_the_examples_are_for_the_course_exam(db_session):
    """Zonder `study.assessment` schreef de generator voor 'een schriftelijk
    tentamen statistiek', het vak waarvoor hij gebouwd is. Dat kreeg applied-ml
    ook, en elk vak van wie de app met eigen vakken gebruikt."""
    _course(db_session, week_plans={"3": {"lectures": [5], "topics": ["linear regression"], "reading": []}})
    _document(db_session)
    client = _FakeClient([_draft()])

    make_examples(db_session, "sso", 3, client=client, figures=False)

    assert "het tentamen van dit vak" in client.instructions[0]
    assert "statistiek voorbereidt" not in client.instructions[0]


def test_an_example_needs_more_than_one_step():
    """Eén stap is geen uitwerking maar een bewering."""
    reden = check_example_draft(_draft(steps=[{"label": "Antwoord", "body": "De helling is -0.8."}]), material=[])

    assert reden is not None and "stappen" in reden


def test_the_self_explanation_question_must_be_a_question():
    reden = check_example_draft(_draft(prompt="Denk hier nog eens over na."), material=[])

    assert reden is not None and "vraag" in reden


def test_the_example_must_rest_on_the_material():
    from app.services.practice.exam_generation import squash

    reden = check_example_draft(
        _draft(source_quote="een zin die nergens staat"), material=[squash(REGRESSIE)]
    )

    assert reden is not None and "citaat" in reden


def test_a_topic_that_already_has_an_example_is_skipped(db_session):
    _course(db_session, week_plans={"3": {"lectures": [5], "topics": ["linear regression"], "reading": []}})
    document = _document(db_session)
    db_session.add(
        Example(
            course_slug="sso", week=3, topic="linear regression", title="bestaat al",
            situation="x", steps=[{"label": "a", "body": "b"}], document_id=document.id, chunk_id="c",
        )
    )
    db_session.commit()
    client = _FakeClient([_draft()])

    report = make_examples(db_session, "sso", 3, client=client, figures=False)

    assert report.created == 0
    assert client.prompts == []


def test_a_figure_that_does_not_draw_costs_the_figure_not_the_example(db_session):
    """Het plaatje is de bonus; de uitwerking is de kern."""
    _course(db_session, week_plans={"3": {"lectures": [5], "topics": ["linear regression"], "reading": []}})
    _document(db_session)
    draft = _draft(figure_code="x = 1", figure_caption="doet niets")

    report = make_examples(db_session, "sso", 3, client=_FakeClient([draft]), figures=True)

    assert report.created == 1
    assert db_session.query(Example).one().figure_svg == ""
    assert any("figuur" in reason for _, reason in report.figure_problems)
