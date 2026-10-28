"""Eén ingang voor alle bestandsformaten: parse_document(path) -> ParsedDocument.

De parser zit bewust achter deze ene functie. Blijkt pypdf de formules in je
tekstboeken te verhaspelen, dan is de vervanging (bijv. pdfplumber) één module
verderop en raakt hij niets anders.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParsedPage:
    page_number: int
    text: str
    # De herhaalde kopregel van deze pagina, zonder paginanummer. In veel
    # tekstboeken staat daar de sectietitel ("Computation on Arrays:
    # Broadcasting"); die is als vindplaats bruikbaar zodra de tekst zelf geen
    # genummerde kop heeft.
    running_header: str | None = None
    # Het pad uit de bladwijzers van de PDF. Dit is de inhoudsopgave zoals de
    # uitgever hem heeft vastgelegd en verslaat elke heuristiek op de tekst.
    outline_path: str | None = None


@dataclass
class ParsedDocument:
    title: str
    page_count: int
    pages: list[ParsedPage]
    metadata: dict[str, str]


_DATE_PREFIX_RE = re.compile(r"^(?:\d{8}|\d{4} \d{2} \d{2})\s+")


def title_from_filename(stem: str) -> str:
    """`20260908_lecture03_data_visualisation` wordt `Lecture03 data visualisation`.

    Hoofdletters blijven staan (`ISLRv2`, niet `Islrv2`), en een datum vooraan
    gaat eraf: die zegt wanneer het college was, niet waar het over gaat, en
    staat al in de weekmap.
    """
    words = " ".join(re.split(r"[_\-\s]+", stem)).strip()
    words = _DATE_PREFIX_RE.sub("", words) or words
    return words[:1].upper() + words[1:]


class UnsupportedFileTypeError(ValueError):
    """Extensie waar geen parser voor bestaat."""


class EmptyDocumentError(ValueError):
    """Het bestand leverde geen bruikbare tekst op (bijv. gescand zonder OCR)."""


_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def repair_surrogates(text: str) -> str:
    """Herstel of verwijder surrogaten die uit de PDF-extractie komen.

    pypdf levert wiskundige tekens uit het astrale vlak (𝒪, 𝑥, U+1D400 en
    verder) soms als halve codepoint aan: de hoge helft van het paar zonder de
    lage. Zo'n string is niet naar UTF-8 te coderen, en de OpenAI-client klapt
    er dus op bij het serialiseren van een heel boek.

    Heen en terug via UTF-16 met `surrogatepass` vouwt geldige paren alsnog tot
    het echte teken. Wat daarna nog los staat mist zijn wederhelft — daar valt
    niets te reconstrueren, dus dat gaat eruit.
    """
    if not _SURROGATE_RE.search(text):
        return text
    folded = text.encode("utf-16", "surrogatepass").decode("utf-16", "surrogatepass")
    return _SURROGATE_RE.sub("", folded)


# Een figuur die pypdf als tekst uitleest: een rug plot wordt "| || | ||| |",
# een spreidingsdiagram "o o o o o". In ISLP levert één zo'n figuur 28 chunks
# van louter pipes op. De ruis eruit strippen in plaats van de chunk weg te
# gooien, want vaak staat er echte alinea vóór of ná de figuur in dezelfde
# chunk. Cijfers blijven buiten schot: anders sneuvelt "100000".
_FIGURE_NOISE_RE = re.compile(r"([^\w\s]|[a-zA-Z])(?:[ \t]?\1){5,}")


def strip_figure_noise(text: str) -> str:
    return _FIGURE_NOISE_RE.sub(" ", text)


_FENCE_LINE_RE = re.compile(r"^\s*(```|~~~)")


def split_code_blocks(text: str) -> list[tuple[bool, str]]:
    """De tekst in stukken: (is_code, tekst), in volgorde.

    Een codeblok loopt van een fence-regel (``` of ~~~) tot de volgende. Zonder
    sluitende fence is het geen blok maar gewone tekst: een losse regel met
    ``` erin, zoals `normalize_text` die per regel krijgt, blijft zo gewoon
    tekst en gedraagt zich als voorheen.
    """
    lines = text.split("\n")
    segments: list[tuple[bool, str]] = []
    prose: list[str] = []
    index = 0
    while index < len(lines):
        if _FENCE_LINE_RE.match(lines[index]):
            close = next((k for k in range(index + 1, len(lines)) if _FENCE_LINE_RE.match(lines[k])), None)
            if close is not None:
                if prose:
                    segments.append((False, "\n".join(prose)))
                    prose = []
                block = [lines[index].strip(), *(line.rstrip() for line in lines[index + 1 : close]), lines[close].strip()]
                segments.append((True, "\n".join(block)))
                index = close + 1
                continue
        prose.append(lines[index])
        index += 1
    if prose:
        segments.append((False, "\n".join(prose)))
    return segments


def _normalize_prose(text: str) -> str:
    text = strip_figure_noise(text)
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_text(text: str) -> str:
    """Tekst opschonen — maar een codeblok niet.

    Proza mag geplet worden: dubbele spaties en afgebroken regels zeggen niets.
    In Python ís de inspringing de betekenis, en welke regels in de lus vallen
    bepaalt wat er geprint wordt. Toen de collegeaantekeningen van SSO deel 2
    erin kwamen stond elk fragment op één regel, en was "wat is de uitvoer"
    niet meer te beantwoorden.
    """
    text = repair_surrogates(text).replace("\x00", " ")
    if "```" not in text and "~~~" not in text:
        return _normalize_prose(text)
    parts: list[str] = []
    for is_code, segment in split_code_blocks(text):
        cleaned = segment if is_code else _normalize_prose(segment)
        if cleaned:
            parts.append(cleaned)
    return "\n\n".join(parts).strip()


def parse_document(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from app.services.parsing.pdf import parse_pdf

        parsed = parse_pdf(path)
    elif suffix == ".pptx":
        from app.services.parsing.pptx import parse_pptx

        parsed = parse_pptx(path)
    elif suffix == ".md":
        from app.services.parsing.markdown import parse_markdown

        parsed = parse_markdown(path)
    elif suffix == ".ipynb":
        from app.services.parsing.notebook import parse_notebook

        parsed = parse_notebook(path)
    elif suffix == ".py":
        from app.services.parsing.notebook import parse_script

        parsed = parse_script(path)
    else:
        raise UnsupportedFileTypeError(f"Geen parser voor '{suffix}'")

    if not parsed.pages:
        raise EmptyDocumentError(
            f"'{path.name}' bevat geen tekstlaag. Gescande pagina's vragen om OCR, "
            "en dat doet fase 1 niet."
        )
    return parsed
