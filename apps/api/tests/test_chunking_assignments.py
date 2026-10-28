from app.services.chunking.assignments import chunk_assignment
from app.services.parsing import ParsedPage


def test_splits_on_exercise_headings():
    page = ParsedPage(
        page_number=1,
        text=(
            "Exercise 1\nBereken de gradiënt van de loss.\n\n"
            "Exercise 2\nBewijs dat de functie convex is.\n\n"
            "Exercise 3\nImplementeer gradient descent."
        ),
    )

    chunks = chunk_assignment([page])

    assert len(chunks) == 3
    assert chunks[0].section_path == "Exercise 1"
    assert "gradiënt" in chunks[0].text
    assert chunks[2].section_path == "Exercise 3"


def test_recognises_dutch_and_alternative_labels():
    page = ParsedPage(page_number=1, text="Opgave 1\nA\n\nVraag 2\nB\n\nProblem 3\nC")

    paths = [chunk.section_path for chunk in chunk_assignment([page])]

    assert paths == ["Opgave 1", "Vraag 2", "Problem 3"]


def test_preamble_before_the_first_exercise_is_kept():
    page = ParsedPage(page_number=1, text="Inleverdatum: vrijdag.\n\nExercise 1\nDoe iets.")

    chunks = chunk_assignment([page])

    assert "Inleverdatum" in chunks[0].text
    assert chunks[0].section_path is None


def test_falls_back_to_windows_without_exercise_headings():
    body = " ".join(f"woord{index}" for index in range(300))
    chunks = chunk_assignment([ParsedPage(page_number=1, text=body)], target_words=100, overlap_words=10)

    assert len(chunks) > 1


def test_long_exercise_is_split_into_windows():
    body = " ".join(f"woord{index}" for index in range(300))
    chunks = chunk_assignment(
        [ParsedPage(page_number=1, text=f"Exercise 1\n{body}")],
        target_words=100,
        overlap_words=10,
    )

    assert len(chunks) > 1
    assert all(chunk.section_path == "Exercise 1" for chunk in chunks)
