from pathlib import Path

import pytest

from app.services.parsing import (
    EmptyDocumentError,
    UnsupportedFileTypeError,
    normalize_text,
    parse_document,
)


def _write_pptx(path: Path, slides: list[tuple[str, list[str]]]) -> None:
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    blank = presentation.slide_layouts[6]
    for title, bullets in slides:
        slide = presentation.slides.add_slide(blank)
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(4))
        frame = box.text_frame
        frame.text = title
        for bullet in bullets:
            frame.add_paragraph().text = bullet
    presentation.save(str(path))


def test_normalize_collapses_whitespace():
    assert normalize_text("a  \t b\n\n\n\nc") == "a b\n\nc"


def test_parses_pptx_one_page_per_slide(tmp_path: Path):
    target = tmp_path / "week-03.pptx"
    _write_pptx(target, [("Gradient Descent", ["stap 1", "stap 2"]), ("Convergentie", ["voorwaarde"])])

    parsed = parse_document(target)

    assert parsed.page_count == 2
    assert [page.page_number for page in parsed.pages] == [1, 2]
    assert "Gradient Descent" in parsed.pages[0].text
    assert "stap 2" in parsed.pages[0].text
    assert parsed.title == "Gradient Descent"


def test_pptx_without_text_raises(tmp_path: Path):
    target = tmp_path / "leeg.pptx"
    _write_pptx(target, [("", [])])

    with pytest.raises(EmptyDocumentError):
        parse_document(target)


def test_unsupported_extension_raises(tmp_path: Path):
    target = tmp_path / "aantekening.txt"
    target.write_text("hallo")

    with pytest.raises(UnsupportedFileTypeError):
        parse_document(target)


def test_repair_surrogates_folds_valid_pairs_into_the_real_character():
    """Een compleet paar is gewoon een teken: 𝒪 hoort te overleven."""
    from app.services.parsing import repair_surrogates

    text = "averages \ud835\udcaa[N log N]"

    assert repair_surrogates(text) == "averages \U0001d4aa[N log N]"


def test_repair_surrogates_drops_the_unpaired_half():
    """pypdf laat bij de Python Data Science Handbook de lage helft vallen.

    Zo'n halve codepoint is niet naar UTF-8 te coderen; er valt niets te
    reconstrueren, dus hij gaat eruit in plaats van een heel boek te blokkeren.
    """
    from app.services.parsing import repair_surrogates

    repaired = repair_surrogates("selection sort averages \ud835 N2")

    assert repaired == "selection sort averages  N2"
    assert repaired.encode("utf-8")


def test_normalize_text_output_is_always_utf8_encodable():
    from app.services.parsing import normalize_text

    assert normalize_text("een \ud835 halve codepoint").encode("utf-8")


def test_normalize_text_leaves_ordinary_text_untouched():
    from app.services.parsing import normalize_text

    assert normalize_text("gewone tekst met accenten: café") == "gewone tekst met accenten: café"


class _FakeBookmark:
    def __init__(self, title: str, page: int) -> None:
        self.title = title
        self.page = page


class _FakeReader:
    """Genoeg van een PdfReader om de bladwijzerlogica te testen."""

    def __init__(self, outline) -> None:
        self.outline = outline

    def get_destination_page_number(self, item) -> int:
        return item.page


def test_outline_paths_are_hierarchical_and_carry_forward():
    """Een pagina zonder eigen bladwijzer hoort bij de sectie die ervoor begon."""
    from app.services.parsing.pdf import _outline_paths_by_page

    outline = [
        _FakeBookmark("Classification", 10),
        [
            _FakeBookmark("Logistic Regression", 12),
            [_FakeBookmark("The Logistic Model", 13)],
        ],
    ]

    paths = _outline_paths_by_page(_FakeReader(outline), page_count=16)

    assert paths[11] == "Classification"
    assert paths[13] == "Classification › Logistic Regression"
    assert paths[14] == "Classification › Logistic Regression › The Logistic Model"
    # Pagina 16 heeft geen eigen bladwijzer en erft de diepste die gold.
    assert paths[16] == "Classification › Logistic Regression › The Logistic Model"
    # Vóór de eerste bladwijzer is er geen vindplaats om te verzinnen.
    assert 1 not in paths


def test_outline_paths_are_empty_without_bookmarks():
    from app.services.parsing.pdf import _outline_paths_by_page

    assert _outline_paths_by_page(_FakeReader([]), page_count=5) == {}


def test_clean_running_header_strips_the_page_number():
    from app.services.parsing.pdf import _clean_running_header

    assert _clean_running_header("64 | Chapter 2: Introduction to NumPy") == (
        "Chapter 2: Introduction to NumPy"
    )
    assert _clean_running_header("Computation on Arrays: Broadcasting | 63") == (
        "Computation on Arrays: Broadcasting"
    )
    assert _clean_running_header("| 63 |") is None


def test_table_of_contents_pages_are_dropped():
    """De inhoudsopgave scoort hoog op precies de vragen waar je het hoofdstuk wil."""
    from app.services.parsing.pdf import _is_table_of_contents

    toc = "\n".join(
        [
            "5 Resampling Methods . . . . . . . . . . 197",
            "5.1 Cross-Validation . . . . . . . . . . 198",
            "5.1.1 The Validation Set Approach . . . . 198",
            "5.1.2 Leave-One-Out Cross-Validation . . 200",
            "5.2 The Bootstrap . . . . . . . . . . . 209",
        ]
    )
    gewoon = "\n".join(
        ["Cross-validation is a resampling method."] * 3
        + ["It estimates test error by holding out folds.", "The result is an estimate of MSE."]
    )

    assert _is_table_of_contents(toc)
    assert not _is_table_of_contents(gewoon)


def test_figure_noise_is_stripped_but_prose_survives():
    """Een rug plot in ISLP leverde 28 chunks van louter pipe-tekens op."""
    from app.services.parsing import strip_figure_noise

    tekst = "Figure 4.2 shows the fit. | || | ||| | |||| || | Logistic regression is used here."

    schoon = strip_figure_noise(tekst)

    assert "|" not in schoon
    assert "Figure 4.2 shows the fit." in schoon
    assert "Logistic regression is used here." in schoon


def test_scatterplot_markers_are_stripped():
    from app.services.parsing import strip_figure_noise

    assert "o" not in strip_figure_noise("o o o o o o o o").strip()


def test_numbers_are_never_touched():
    """"100000" bevat vijf nullen op een rij; die mag hij niet opeten."""
    from app.services.parsing import strip_figure_noise

    for getal in ("100000", "0.000001", "1000000 observations", "2.9222222"):
        assert getal in strip_figure_noise(getal)


def test_ordinary_punctuation_survives():
    from app.services.parsing import strip_figure_noise

    for tekst in ("wacht... echt?", "a -- b", "x**2", "e.g. see [1]", "aa bb cc"):
        assert strip_figure_noise(tekst) == tekst


def test_a_horizontal_rule_is_noise():
    from app.services.parsing import strip_figure_noise

    assert "-" not in strip_figure_noise("kop\n--------\ntekst")


# --- cijfers die als glyphnaam uit de PDF komen ------------------------------


def test_glyph_names_become_digits_again():
    """Letterlijk zoals pypdf het proeftentamen van FDS uitleest."""
    from app.services.parsing.pdf import repair_glyph_names

    pagina = (
        "/one.pnum./five.pnump\n/three.pnumc\nWhat is the False Negative Rate?\n"
        "a 6//one.pnum/one.pnumb /five.pnum/6c /one.pnum/6d /five.pnum//one.pnum/one.pnum"
    )

    (hersteld,) = repair_glyph_names([pagina])

    assert hersteld.startswith("1.5p\n3c\n")
    assert "a 6/11b 5/6c 1/6d 5/11" in hersteld


def test_a_fraction_between_two_glyph_names_keeps_its_slash():
    from app.services.parsing.pdf import repair_glyph_names

    (hersteld,) = repair_glyph_names(["a /three.pnum//five.pnumb /three.pnum//two.pnumc /two.pnum//five.pnum"])

    assert hersteld == "a 3/5b 3/2c 2/5"


def test_a_document_without_the_font_problem_is_left_alone():
    """Een losse `/one` in een URL is geen glyphnaam."""
    from app.services.parsing.pdf import repair_glyph_names

    tekst = ["zie https://example.org/one and/or /five things"]

    assert repair_glyph_names(tekst) == tekst


def test_the_evidence_may_come_from_another_page():
    """Een paginanummer als `/one` wordt ook hersteld zodra het document zelf
    elders laat zien dat zijn lettertype dit doet."""
    from app.services.parsing.pdf import repair_glyph_names

    paginas = ["/one.pnum/two.pnum/three.pnum", "pagina /four / /one"]

    assert repair_glyph_names(paginas) == ["123", "pagina 4 / 1"]


# --- titels die een deck van de andere onderscheiden ----------------------------


@pytest.mark.parametrize(
    ("stem", "titel"),
    [
        ("20260908_lecture03_data_visualisation", "Lecture03 data visualisation"),
        ("2026_09_01_Lecture1", "Lecture1"),
        ("ISLRv2_corrected_June_2023", "ISLRv2 corrected June 2023"),
        ("Python-Data-Science-Handbook", "Python Data Science Handbook"),
    ],
)
def test_a_title_from_a_filename_keeps_its_case_and_drops_the_date(stem, titel):
    from app.services.parsing import title_from_filename

    assert title_from_filename(stem) == titel


@pytest.mark.parametrize(
    "metadata",
    ["PowerPoint Presentation", "Microsoft PowerPoint - Presentation1", "Untitled document", "Slides"],
)
def test_a_placeholder_title_falls_back_to_the_filename(metadata):
    from app.services.parsing.pdf import _infer_title

    assert _infer_title({"Title": metadata}, Path("2026_09_03_Lecture2.pdf")) == "Lecture2"


def test_an_office_prefix_is_stripped_from_a_real_title():
    from app.services.parsing.pdf import _infer_title

    assert _infer_title({"Title": "Microsoft Word - Assignment 1"}, Path("a.pdf")) == "Assignment 1"


def test_a_real_metadata_title_still_wins():
    from app.services.parsing.pdf import _infer_title

    assert _infer_title({"Title": "What is the question?"}, Path("2015-Peng-Science.pdf")) == "What is the question?"


def test_a_series_title_on_a_lecture_deck_gives_way_to_the_filename():
    """Colleges 3 en 4 van FDS droegen allebei de titel van het vak, en de
    titel is de wortel van elk sectiepad in het deck."""
    from app.services.chunking.slides import deck_title

    vak = "Fundamentals of Data Science - Master Information Studies - Data Science track"

    assert deck_title(vak, "20260908_lecture03_data_visualisation") == "Lecture03 data visualisation"
    assert deck_title("Lecture 3", "lecture3") == "Lecture 3"
    assert deck_title("Introduction to Pandas", "pandas_intro") == "Introduction to Pandas"


# --- markdown ---------------------------------------------------------------


def test_markdown_becomes_one_page_per_heading_with_its_path(tmp_path: Path):
    """Een markdownbestand heeft geen pagina's; de koppen zijn de structuur.
    Het kopjespad gaat mee als `outline_path`, zoals de bladwijzers van een PDF."""
    path = tmp_path / "quiz-01.md"
    path.write_text(
        "# Quiz 1 — Pandas\n\nIntro over de quiz.\n\n"
        "## Vraag 1 — één antwoord\n\nHoe maak je een kolom?\n\n- [ ] `df.add('x')`\n\n"
        "<!-- antwoord: nog niet vrijgegeven -->\n\n"
        "## Vraag 2\n\n### Deel a\n\nWat doet `loc`?\n",
        encoding="utf-8",
    )

    parsed = parse_document(path)

    assert parsed.title == "Quiz 1 — Pandas"
    assert parsed.metadata["source_format"] == "markdown"
    assert [page.outline_path for page in parsed.pages] == [
        "Quiz 1 — Pandas",
        "Quiz 1 — Pandas › Vraag 1 — één antwoord",
        "Quiz 1 — Pandas › Vraag 2 › Deel a",
    ]
    assert [page.page_number for page in parsed.pages] == [1, 2, 3]
    # normalize_text maakt van een gedachtestreepje een koppelteken, net als bij PDF.
    assert parsed.pages[1].text.startswith("Vraag 1 - één antwoord\n")
    assert "Hoe maak je een kolom?" in parsed.pages[1].text
    assert "antwoord: nog niet" not in parsed.pages[1].text


def test_markdown_without_headings_is_one_page_titled_after_the_file(tmp_path: Path):
    path = tmp_path / "20260917_aantekeningen_regressie.md"
    path.write_text("Gewoon tekst.\nNog een regel.\n", encoding="utf-8")

    parsed = parse_document(path)

    assert parsed.title == "Aantekeningen regressie"
    assert len(parsed.pages) == 1
    assert parsed.pages[0].outline_path is None


def test_a_hash_inside_a_code_block_is_not_a_heading(tmp_path: Path):
    path = tmp_path / "lab.md"
    path.write_text("# Lab 3\n\n```python\n# een commentaar\nx = 1\n```\n", encoding="utf-8")

    parsed = parse_document(path)

    assert len(parsed.pages) == 1
    assert "# een commentaar" in parsed.pages[0].text


def test_markdown_with_only_a_comment_is_empty(tmp_path: Path):
    path = tmp_path / "leeg.md"
    path.write_text("<!-- alleen commentaar -->\n\n", encoding="utf-8")

    with pytest.raises(EmptyDocumentError):
        parse_document(path)
