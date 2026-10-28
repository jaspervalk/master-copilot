"""De samenvatting raakt OpenAI niet, maar haalt het materiaal wél echt op:
dat een samenvatting álle stof van de week ziet is de hele reden dat je hem
kunt vertrouwen."""
import pytest

from app.models import Chunk, Course, Document, WeekSummary
from app.services.weeks_summary import (
    MAX_SOURCE_CHARS,
    NoWeekMaterial,
    SummaryDraft,
    Topic,
    build_summary,
    is_stale,
    week_material,
)


def _document(db, *, course="sso", title="Lecture 1", kind="slides", week=1,
              path=None, sections=(("Lecture 1 › slide 1", 1),), text="stof", status=None):
    document = Document(
        title=title, source_path=path or f"{course}/slides/week-0{week or 1}/{title}.pdf",
        checksum=title.ljust(64, "0"), course_slug=course, doc_kind=kind, week=week,
        assignment_status=status, ingestion_status="indexed",
    )
    for index, (section, page) in enumerate(sections):
        document.chunks.append(Chunk(
            chunk_index=index, section_path=section, page_start=page, page_end=page,
            token_count=3, text=text, normalized_text=text, chunk_metadata={},
        ))
    db.add(document)
    db.commit()
    return document


class _FakeClient:
    def __init__(self, draft):
        self.calls = []
        outer = self

        class _Responses:
            def parse(self, *, model, instructions, input, text_format):
                outer.calls.append({"instructions": instructions, "input": input})
                return type("Parsed", (), {"output_parsed": draft})()

        self.responses = _Responses()


DRAFT = SummaryDraft(
    thread="Deze week gaat over toetsen.",
    topics=[Topic(label="Lecture 1", covers="Hypothesetoetsen.", where="slides 1-20")],
    concepts=[],
    skills=["een t-toets uitvoeren"],
)


def test_the_lectures_of_that_week_are_the_material(db_session):
    _document(db_session, week=1)
    _document(db_session, title="Lecture 9", week=2, sections=(("Lecture 9 › slide 1", 1),))

    material = week_material(db_session, "sso", 1)

    assert [chunk.section_path for chunk in material.chunks] == ["Lecture 1 › slide 1"]


def test_the_book_chapters_of_the_week_plan_are_included(db_session):
    _document(db_session, week=1)
    boek = _document(
        db_session, title="Triola", kind="book", week=None, path="sso/books/Triola.pdf",
        sections=(("9 Inferences › 9.2 Two Proportions", 340), ("12 Iets anders", 500)),
    )
    db_session.add(Course(slug="sso", name="SSO", week_plans={
        "1": {"reading": [{"document": "sso/books/Triola.pdf", "sections": ["9.2"]}]}
    }))
    db_session.commit()

    material = week_material(db_session, "sso", 1)

    paden = [chunk.section_path for chunk in material.chunks]
    assert "9 Inferences › 9.2 Two Proportions" in paden
    assert "12 Iets anders" not in paden
    assert boek.id  # het boek zelf heeft geen week; het komt via het leesplan mee


def test_a_solution_from_an_open_week_stays_out(db_session):
    """Dezelfde spoilerregel als bij een vraag: een samenvatting is ook een
    manier om een uitwerking te lezen."""
    _document(db_session, week=1)
    _document(db_session, title="Assignment 1", kind="assignment", week=1,
              status="open", sections=(("Opgave 1", 1),))
    _document(db_session, title="Uitwerking", kind="solution", week=1,
              sections=(("Antwoord 1", 1),))

    material = week_material(db_session, "sso", 1)

    paden = {chunk.section_path for chunk in material.chunks}
    assert paden == {"Lecture 1 › slide 1", "Opgave 1"}


def test_the_material_stops_at_the_budget_and_says_so(db_session):
    lang = "w" * (MAX_SOURCE_CHARS // 3 + 1)
    _document(db_session, week=1, text=lang,
              sections=tuple((f"Lecture 1 › slide {n}", n) for n in range(1, 6)))

    material = week_material(db_session, "sso", 1)

    assert len(material.chunks) == 2
    assert material.total == 5


def test_the_lectures_survive_and_the_reading_is_thinned_out(db_session):
    """Van achteren afkappen zou het laatste hoofdstuk van een week volledig
    laten verdwijnen zonder dat de samenvatting doorheeft dat het bestond."""
    lang = "w" * (MAX_SOURCE_CHARS // 4)
    _document(db_session, week=1, text=lang,
              sections=tuple((f"Lecture 1 › slide {n}", n) for n in range(1, 4)))
    _document(db_session, title="Triola", kind="book", week=None, text=lang,
              path="sso/books/Triola.pdf",
              sections=tuple((f"9.{n} Sectie", 300 + n) for n in range(1, 9)))
    db_session.add(Course(slug="sso", name="SSO", week_plans={
        "1": {"reading": [{"document": "sso/books/Triola.pdf", "sections": ["9."]}]}
    }))
    db_session.commit()

    material = week_material(db_session, "sso", 1)
    paden = [chunk.section_path for chunk in material.chunks]

    # Alle colleges erin, en de leesstof uitgedund over het hele hoofdstuk
    # in plaats van alleen de eerste secties.
    assert paden[:3] == ["Lecture 1 › slide 1", "Lecture 1 › slide 2", "Lecture 1 › slide 3"]
    boek = [pad for pad in paden if pad.startswith("9.")]
    assert boek and boek[-1] != "9.2 Sectie"


def test_a_summary_is_stored_with_what_it_was_made_from(db_session):
    _document(db_session, week=1)

    summary = build_summary(db_session, course_slug="sso", week=1, client=_FakeClient(DRAFT))

    assert summary.content["thread"] == "Deze week gaat over toetsen."
    assert (summary.chunks_used, summary.chunks_total) == (1, 1)
    assert db_session.get(WeekSummary, ("sso", 1)) is not None


def test_regenerating_replaces_instead_of_duplicating(db_session):
    _document(db_session, week=1)
    build_summary(db_session, course_slug="sso", week=1, client=_FakeClient(DRAFT))
    build_summary(db_session, course_slug="sso", week=1, client=_FakeClient(DRAFT))

    assert db_session.query(WeekSummary).count() == 1


def test_new_material_makes_a_summary_stale(db_session):
    _document(db_session, week=1)
    summary = build_summary(db_session, course_slug="sso", week=1, client=_FakeClient(DRAFT))
    assert not is_stale(db_session, summary)

    _document(db_session, title="Lecture 2", week=1, sections=(("Lecture 2 › slide 1", 1),))

    assert is_stale(db_session, summary)


def test_a_week_without_material_is_a_clear_error(db_session):
    with pytest.raises(NoWeekMaterial):
        build_summary(db_session, course_slug="sso", week=4, client=_FakeClient(DRAFT))


def test_the_prompt_carries_the_topics_from_the_course_guide(db_session):
    """Het materiaal noemt een onderwerp soms anders dan de studiewijzer."""
    _document(db_session, week=1)
    db_session.add(Course(slug="sso", name="SSO", week_plans={"1": {"topics": ["descriptive statistics"]}}))
    db_session.commit()
    client = _FakeClient(DRAFT)

    build_summary(db_session, course_slug="sso", week=1, client=client)

    assert "descriptive statistics" in client.calls[0]["input"]


def test_material_can_be_asked_for_unthinned(db_session, monkeypatch):
    """De uitdunning is er voor één prompt. Wie per onderwerp kaarten maakt,
    filtert zelf en heeft juist álles nodig: bij FDS week 4 sneuvelde een paper
    van twaalf fragmenten volledig, en dan lijkt 'link prediction' stof te
    missen die er wel is."""
    from app.services.weeks_summary import MAX_SOURCE_CHARS, week_material

    course = Course(slug="fds", name="FDS", week_plans={"4": {"lectures": [], "topics": [], "reading": []}})
    db_session.add(course)
    document = Document(
        title="Lecture 7", source_path="fds/slides/week-04/lecture7.pdf", checksum="z" * 64,
        course_slug="fds", doc_kind="slides", week=4, ingestion_status="indexed",
    )
    lang = "netwerk " * 2000
    for index in range(40):
        document.chunks.append(
            Chunk(chunk_index=index, section_path=f"Lecture 7 › slide {index}", page_start=index + 1,
                  page_end=index + 1, token_count=500, text=lang, normalized_text=lang, chunk_metadata={})
        )
    db_session.add(document)
    db_session.commit()

    gedund = week_material(db_session, "fds", 4)
    alles = week_material(db_session, "fds", 4, fit=False)

    assert len(alles.chunks) == 40
    assert len(gedund.chunks) <= len(alles.chunks)


def _formule(**overrides):
    from app.services.weeks_summary import Formula, Symbol

    velden = dict(
        name="Toetsingsgrootheid van de eensteekproefs t-toets",
        latex=r"t = \frac{\bar x - \mu_0}{s/\sqrt{n}}",
        when="Als je toetst of een gemiddelde afwijkt van een waarde en sigma onbekend is.",
        symbols=[Symbol(symbol=r"\bar x", meaning="het steekproefgemiddelde")],
    )
    velden.update(overrides)
    return Formula(**velden)


def test_a_formula_needs_its_symbols_explained():
    """Een formule zonder uitleg van de symbolen is een plaatje, geen hulp."""
    from app.services.weeks_summary import formula_problem

    assert formula_problem(_formule(symbols=[]), material=["t toets"]) is not None
    assert "symbolen" in formula_problem(_formule(symbols=[]), material=["t toets"])


def test_a_formula_without_latex_is_dropped():
    from app.services.weeks_summary import formula_problem

    assert formula_problem(_formule(latex="  "), material=["t toets"]) is not None


def test_a_formula_needs_to_say_when_you_use_it():
    from app.services.weeks_summary import formula_problem

    assert formula_problem(_formule(when="  ")) is not None


def test_the_name_is_not_checked_against_the_material():
    """De weekkaart is Nederlands en de slides zijn Engels, dus "Kleinste-
    kwadraten schatters" staat nergens in het materiaal. Een eerdere versie
    controleerde dat wél en gooide dertien van de vijftien goede formules weg.
    De herkomst wordt begrensd door de invoer: het model ziet alleen de
    fragmenten van deze week."""
    from app.services.weeks_summary import formula_problem

    assert formula_problem(_formule(), material=["something entirely in english"]) is None


def test_a_code_free_course_gets_different_instructions(db_session):
    """Een tentamen zonder code: een weekkaart die 'fit met lm()' als vaardigheid
    opschrijft, oefent je op iets wat niet gevraagd wordt."""
    from app.services.weeks_summary import instructions_for

    db_session.add(Course(slug="sso", name="SSO", study={"code": "none"}))
    db_session.add(Course(slug="fds", name="FDS", study={}))
    db_session.commit()

    zonder_code = instructions_for(db_session, "sso")
    met_code = instructions_for(db_session, "fds")

    assert "met de hand" in zonder_code
    assert "lm(" in zonder_code  # als voorbeeld van wat er níet in mag
    assert "met de hand" not in met_code


def test_a_course_that_asks_to_read_code_says_predict_the_output(db_session):
    """Bij SSO deel 2: 'wat is de uitvoer van dit fragment'. Lezen en voorspellen
    hoort dan bij de vaardigheden, syntax uit je hoofd schrijven niet."""
    from app.services.weeks_summary import instructions_for

    db_session.add(Course(slug="sso", name="SSO", study={"code": "read"}))
    db_session.commit()

    tekst = instructions_for(db_session, "sso")

    assert "uitvoer" in tekst
    assert "voorspel" in tekst
    assert "syntax" in tekst


def test_a_course_that_does_not_exist_gets_the_normal_instructions(db_session):
    from app.services.weeks_summary import INSTRUCTIONS, instructions_for

    assert instructions_for(db_session, "bestaat-niet") == INSTRUCTIONS
