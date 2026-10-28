from app.services.chunking.slides import chunk_slides
from app.services.parsing import ParsedPage


def _slide(number: int, text: str) -> ParsedPage:
    return ParsedPage(page_number=number, text=text)


def _long(words: int) -> str:
    return " ".join(f"woord{index}" for index in range(words))


def test_one_chunk_per_slide():
    pages = [_slide(1, f"Gradient Descent\n{_long(40)}"), _slide(2, f"Convergentie\n{_long(40)}")]

    chunks = chunk_slides(pages, deck_title="Week 3")

    assert len(chunks) == 2
    assert chunks[0].page_start == chunks[0].page_end == 1
    assert chunks[1].page_start == chunks[1].page_end == 2


def test_section_path_names_deck_and_slide():
    chunks = chunk_slides([_slide(7, f"Backprop\n{_long(40)}")], deck_title="Week 3 — Neurale netwerken")

    assert chunks[0].section_path == "Week 3 — Neurale netwerken › slide 7"
    assert chunks[0].chunk_metadata["slide_number"] == 7


def test_short_slide_merges_into_the_next():
    pages = [_slide(1, "Vragen?"), _slide(2, f"Regularisatie\n{_long(40)}")]

    chunks = chunk_slides(pages, deck_title="Week 4")

    assert len(chunks) == 1
    assert "Vragen?" in chunks[0].text
    assert "Regularisatie" in chunks[0].text
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 2


def test_trailing_short_slide_still_produces_a_chunk():
    pages = [_slide(1, f"Inhoud\n{_long(40)}"), _slide(2, "Bedankt!")]

    chunks = chunk_slides(pages, deck_title="Week 5")

    assert len(chunks) == 2
    assert chunks[1].text.endswith("Bedankt!")


def test_chunk_indexes_are_sequential():
    pages = [_slide(number, f"Kop {number}\n{_long(30)}") for number in range(1, 5)]

    assert [chunk.chunk_index for chunk in chunk_slides(pages, deck_title="Deck")] == [0, 1, 2, 3]
