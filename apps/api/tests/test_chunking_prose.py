from app.services.chunking.common import heading_level, looks_like_heading, word_count
from app.services.chunking.prose import chunk_prose
from app.services.parsing import ParsedPage


def _page(number: int, text: str) -> ParsedPage:
    return ParsedPage(page_number=number, text=text)


def test_heading_level_counts_numbering_depth():
    assert heading_level("5 Neural Networks") == 1
    assert heading_level("5.3 Error Backpropagation") == 2
    assert heading_level("5.3.1 Evaluation") == 3
    assert heading_level("Gewoon een zin zonder nummer") is None


def test_looks_like_heading_accepts_numbered_and_uppercase():
    assert looks_like_heading("5.3 Error Backpropagation")
    assert looks_like_heading("APPENDIX A")
    assert not looks_like_heading(
        "Dit is een gewone alinea die veel te lang is om als kop door te gaan in welk boek dan ook."
    )


def test_section_path_is_hierarchical():
    pages = [
        _page(
            1,
            "5 Neural Networks\n\n"
            "Inleidende alinea over netwerken.\n\n"
            "5.3 Error Backpropagation\n\n"
            "De kettingregel toegepast op de lagen.",
        )
    ]

    chunks = chunk_prose(pages)

    # Korte secties worden samengepakt: één chunk, gelabeld waar hij begint.
    # De subsectie waar hij doorheen loopt blijft in de metadata staan, anders
    # kun je een citaat niet nauwkeuriger maken dan het hoofdstuk.
    assert chunks[0].section_path == "5 Neural Networks"
    assert chunks[0].chunk_metadata["sections"] == [
        "5 Neural Networks",
        "5 Neural Networks › 5.3 Error Backpropagation",
    ]


def test_deeper_heading_replaces_sibling_not_parent():
    pages = [
        _page(1, "5 Neural Networks\n\nA\n\n5.3 Backprop\n\nB\n\n5.4 Regularisatie\n\nC"),
    ]

    chunks = chunk_prose(pages)
    covered = chunks[-1].chunk_metadata["sections"]

    assert covered[-1] == "5 Neural Networks › 5.4 Regularisatie"
    # 5.4 vervangt 5.3 op zijn eigen diepte in plaats van het hoofdstuk weg te
    # duwen; het pad van de laatste sectie bevat dus geen 5.3 meer.
    assert "5.3" not in covered[-1]


def test_windows_respect_target_and_overlap():
    body = " ".join(f"woord{index}" for index in range(1000))
    chunks = chunk_prose([_page(1, f"1 Hoofdstuk\n\n{body}")], target_words=100, overlap_words=20)

    assert len(chunks) > 1
    assert all(word_count(chunk.text) <= 110 for chunk in chunks)
    first_words = chunks[0].text.split()
    second_words = chunks[1].text.split()
    assert set(first_words) & set(second_words)


def test_page_span_reflects_words_in_the_window():
    chunks = chunk_prose(
        [_page(1, "1 Kop\n\n" + " ".join(["alpha"] * 50)), _page(2, " ".join(["beta"] * 50))],
        target_words=200,
        overlap_words=0,
    )

    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 2


def test_empty_input_returns_no_chunks():
    assert chunk_prose([]) == []


def test_headings_are_found_without_blank_lines():
    """PDF-extractie levert vaak geen lege regels tussen alinea's.

    Zonder regel-voor-regel kopherkenning zou elke chunk van een hoofdstuk dan
    zonder vindplaats eindigen — precies wat een citaat onnaslaanbaar maakt.
    """
    page = _page(
        1,
        "5 Neurale netwerken\n"
        "Een netwerk stapelt lineaire transformaties met daartussen niet-lineariteit.\n"
        "5.3 Error backpropagation\n"
        "Backpropagation past de kettingregel laag voor laag toe.",
    )

    chunks = chunk_prose([page])

    assert chunks[0].section_path == "5 Neurale netwerken"
    assert chunks[0].chunk_metadata["sections"][-1] == (
        "5 Neurale netwerken › 5.3 Error backpropagation"
    )


def test_a_sentence_starting_with_a_number_is_not_a_heading():
    page = _page(1, "1 Inleiding\n1998 was een druk jaar voor het vakgebied.\nDaarna ging het snel.")

    chunks = chunk_prose([page])

    assert all(chunk.section_path == "1 Inleiding" for chunk in chunks)
    assert "1998" in chunks[0].text


def test_short_sections_are_packed_instead_of_becoming_fragments():
    """Elke tussenkop een eigen chunk geven leverde chunks van veertig woorden op.

    Op een echt tekstboek was de mediaan 43 woorden bij een doel van 425: te
    weinig context om een vraag mee te beantwoorden.
    """
    tekst = "\n".join(
        f"{index} Kopje {index}\n" + " ".join(["woord"] * 30) for index in range(1, 10)
    )

    chunks = chunk_prose([_page(1, tekst)], target_words=200, overlap_words=0)

    assert len(chunks) < 9
    assert word_count(chunks[0].text) >= 120


def test_a_section_break_still_wins_once_the_chunk_has_body():
    """Een sectiegrens is de mooiste knipplek zodra er genoeg in de chunk zit."""
    tekst = (
        "1 Eerste\n" + " ".join(["alpha"] * 180) + "\n"
        "2 Tweede\n" + " ".join(["beta"] * 180)
    )

    chunks = chunk_prose([_page(1, tekst)], target_words=250, overlap_words=0)

    assert len(chunks) == 2
    assert chunks[0].section_path == "1 Eerste"
    assert chunks[1].section_path == "2 Tweede"
    assert "beta" not in chunks[0].text
    assert "alpha" not in chunks[1].text


def test_no_trailing_chunk_made_only_of_overlap():
    """Een document dat precies op een chunkgrens eindigt gaf een duplicaat."""
    body = " ".join(f"woord{index}" for index in range(200))

    chunks = chunk_prose([_page(1, f"1 Kop\n{body}")], target_words=100, overlap_words=20)

    laatste = chunks[-1].text.split()
    voorlaatste = set(chunks[-2].text.split())
    assert not set(laatste) <= voorlaatste, "laatste chunk voegt niets nieuws toe"


def _page_with(page_number, text, *, outline=None, header=None):
    return ParsedPage(
        page_number=page_number, text=text, outline_path=outline, running_header=header
    )


def test_outline_path_wins_over_heading_guessing():
    """Met bladwijzers is elke gok op de tekst alleen maar slechter."""
    page = _page_with(
        1,
        "10 loops, best of 3: 135 ms per loop\n" + " ".join(["woord"] * 60),
        outline="Chapter 2. NumPy › Sorting Arrays",
    )

    chunks = chunk_prose([page], target_words=200, overlap_words=0)

    assert len(chunks) == 1
    assert chunks[0].section_path == "Chapter 2. NumPy › Sorting Arrays"
    # De valse kop hoort gewoon bij de tekst en knipt hem dus niet in tweeën.
    assert "10 loops" in chunks[0].text


def test_running_header_is_the_fallback_without_an_outline():
    page = _page_with(
        1, " ".join(["woord"] * 60), header="Computation on Arrays: Broadcasting"
    )

    chunks = chunk_prose([page], target_words=200, overlap_words=0)

    assert chunks[0].section_path == "Computation on Arrays: Broadcasting"
