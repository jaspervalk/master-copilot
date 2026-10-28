import pytest

from app.services.chunking import chunk_document
from app.services.parsing import ParsedDocument, ParsedPage


def _parsed(pages: list[ParsedPage], title: str = "Deck") -> ParsedDocument:
    return ParsedDocument(title=title, page_count=len(pages), pages=pages, metadata={})


def test_slides_get_one_chunk_per_slide():
    pages = [ParsedPage(page_number=n, text=f"Kop {n}\n" + " ".join(["w"] * 40)) for n in (1, 2)]

    chunks = chunk_document(doc_kind="slides", parsed=_parsed(pages, title="Week 3"))

    assert len(chunks) == 2
    assert chunks[0].section_path.startswith("Week 3")


def test_assignments_split_on_exercises():
    pages = [ParsedPage(page_number=1, text="Exercise 1\nA\n\nExercise 2\nB")]

    chunks = chunk_document(doc_kind="assignment", parsed=_parsed(pages))

    assert [chunk.section_path for chunk in chunks] == ["Exercise 1", "Exercise 2"]


@pytest.mark.parametrize("doc_kind", ["submission", "solution"])
def test_submissions_and_solutions_use_the_assignment_chunker(doc_kind):
    pages = [ParsedPage(page_number=1, text="Opgave 1\nMijn uitwerking")]

    chunks = chunk_document(doc_kind=doc_kind, parsed=_parsed(pages))

    assert chunks[0].section_path == "Opgave 1"


@pytest.mark.parametrize("doc_kind", ["book", "paper", "note"])
def test_prose_kinds_use_the_window_chunker(doc_kind):
    pages = [ParsedPage(page_number=1, text="5 Kop\n\n" + " ".join(["woord"] * 600))]

    chunks = chunk_document(doc_kind=doc_kind, parsed=_parsed(pages))

    assert len(chunks) > 1
    assert chunks[0].section_path == "5 Kop"


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        chunk_document(doc_kind="verzonnen", parsed=_parsed([ParsedPage(page_number=1, text="x")]))


def test_exercise_uses_the_assignment_chunker():
    from app.services.chunking import chunk_document
    from app.services.parsing import ParsedDocument, ParsedPage

    parsed = ParsedDocument(
        title="Huiswerk", page_count=1, metadata={},
        pages=[ParsedPage(page_number=1, text="Opgave 1\nBereken het gemiddelde.\nOpgave 2\nBereken de variantie.")],
    )

    chunks = chunk_document(doc_kind="exercise", parsed=parsed)

    assert [c.section_path for c in chunks] == ["Opgave 1", "Opgave 2"]


def test_markdown_exercises_are_split_on_their_headings():
    """'Vraag 1 — één antwoord · 1 punt' is geen kale 'Vraag 1', en een
    markdownbestand is al per kop opgeknipt: de koppen zijn de opgaven."""
    pages = [
        ParsedPage(page_number=1, text="Quiz 1\nIntro.", outline_path="Quiz 1"),
        ParsedPage(page_number=2, text="Vraag 1 — één antwoord\nHoe maak je een kolom?", outline_path="Quiz 1 › Vraag 1 — één antwoord"),
        ParsedPage(page_number=3, text="Vraag 2 — meerdere antwoorden\nWat doet loc?", outline_path="Quiz 1 › Vraag 2 — meerdere antwoorden"),
    ]
    parsed = ParsedDocument(title="Quiz 1", page_count=3, pages=pages, metadata={"source_format": "markdown"})

    chunks = chunk_document(doc_kind="exercise", parsed=parsed)

    assert [chunk.section_path for chunk in chunks] == [
        "Quiz 1",
        "Quiz 1 › Vraag 1 — één antwoord",
        "Quiz 1 › Vraag 2 — meerdere antwoorden",
    ]
    assert chunks[1].text.startswith("Vraag 1 - één antwoord\n")
    assert "Hoe maak je een kolom?" in chunks[1].text
    assert chunks[1].page_start == 2
