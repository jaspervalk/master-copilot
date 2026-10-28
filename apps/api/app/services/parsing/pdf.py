"""PDF-tekstextractie met pypdf.

Herhaalde kop- en voetregels worden eruit gefilterd: in een tekstboek staat op
elke pagina de hoofdstuktitel, en die zou anders elke chunk vervuilen.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

from app.services.parsing import ParsedDocument, ParsedPage, normalize_text, title_from_filename


# Zelfde scheidingsteken als de chunker gebruikt, zodat een bladwijzerpad en een
# afgeleid sectiepad er hetzelfde uitzien.
SECTION_SEPARATOR = " › "


def _first_non_empty_line(text: str) -> str | None:
    for line in text.splitlines():
        candidate = normalize_text(line)
        if candidate:
            return candidate
    return None


def _last_non_empty_line(text: str) -> str | None:
    for line in reversed(text.splitlines()):
        candidate = normalize_text(line)
        if candidate:
            return candidate
    return None


_DIGITS_RE = re.compile(r"\d+")
# Puntreeksen tussen titel en paginanummer: het handtekeningpatroon van een
# inhoudsopgave.
_DOT_LEADER_RE = re.compile(r"\.\s*\.\s*\.")


def _signature(line: str) -> str:
    """Een kopregel zonder zijn paginanummer.

    "64 | Chapter 2: Introduction to NumPy" en "66 | Chapter 2: Introduction to
    NumPy" zijn dezelfde kopregel. Op de letterlijke tekst tellen levert honderd
    unieke regels op die elk één keer voorkomen, en dan wordt er niets gestript.
    """
    return _DIGITS_RE.sub("#", line)


def _common_edge_lines(page_texts: list[str], extractor) -> set[str]:
    """Handtekeningen die op genoeg pagina's op dezelfde plek staan.

    De drempel is bewust laag: een kopregel hoort bij een hoofdstuk, niet bij
    het hele boek, dus "op de helft van alle pagina's" mist ze allemaal.
    """
    values = [value for text in page_texts if (value := extractor(text))]
    counts = Counter(_signature(value) for value in values)
    threshold = max(3, len(page_texts) // 20)
    return {
        signature
        for signature, count in counts.items()
        if count >= threshold and len(signature.split()) <= 12
    }


def _is_table_of_contents(text: str) -> bool:
    """Een pagina die vooral uit puntreeksen bestaat is een inhoudsopgave.

    Die staat vol kopteksten en scoort daardoor hoog op precies de vragen waar
    je het hoofdstuk zelf wil hebben — een kruimelpad naar een kruimelpad.
    """
    # Bewust op de ruwe regels: `normalize_text` strijkt figuurruis weg en
    # neemt de puntreeksen mee waar deze detectie juist op leunt.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 5:
        return False
    with_leaders = sum(1 for line in lines if _DOT_LEADER_RE.search(line))
    return with_leaders / len(lines) >= 0.3


# "64 | Chapter 2: Introduction to NumPy" en "Computation on Arrays:
# Broadcasting | 63" — het paginanummer staat links of rechts van een scheiding.
_HEADER_NOISE_RE = re.compile(r"^[\d\s|·•—–-]+|[\d\s|·•—–-]+$")


def _clean_running_header(line: str) -> str | None:
    """Haal het paginanummer en de scheidingstekens van een kopregel af."""
    stripped = _HEADER_NOISE_RE.sub("", line).strip()
    # Alleen bruikbaar als er een echt woord overblijft; "| 63 |" is geen titel.
    if len(stripped) < 4 or not any(len(w) >= 3 and w.isalpha() for w in stripped.split()):
        return None
    return stripped


def _strip_common_headers_and_footers(page_texts: list[str]) -> list[tuple[str, str | None]]:
    """Geef per pagina de opgeschoonde tekst plus de kopregel die eraf ging."""
    headers = _common_edge_lines(page_texts, _first_non_empty_line)
    footers = _common_edge_lines(page_texts, _last_non_empty_line)
    cleaned_pages: list[tuple[str, str | None]] = []

    for text in page_texts:
        if _is_table_of_contents(text):
            cleaned_pages.append(("", None))
            continue
        lines = [normalize_text(line) for line in text.splitlines()]
        lines = [line for line in lines if line]

        header: str | None = None
        if lines and _signature(lines[0]) in headers:
            header = _clean_running_header(lines[0])
            lines = lines[1:]
        if lines and _signature(lines[-1]) in footers:
            # De voetregel is soms de titel en de kopregel het paginanummer.
            header = header or _clean_running_header(lines[-1])
            lines = lines[:-1]

        cleaned_pages.append(("\n".join(lines).strip(), header))

    return cleaned_pages


# Exportprogramma's vullen het titelveld vaak met een nietszeggende
# plaatshouder, die als vindplaats onbruikbaar is. Herkend aan de woorden en
# niet aan exacte gelijkheid: "PowerPoint Presentation" glipte door een lijst
# met "powerpoint" en "presentation" los, en twee colleges met die titel
# belandden in één deck.
_GENERIC_TITLE_WORDS = frozenset(
    {"untitled", "unnamed", "document", "presentation", "microsoft", "word", "powerpoint", "slide", "slides", "keynote", "pdf"}
)
_OFFICE_PREFIX_RE = re.compile(r"^microsoft (?:word|powerpoint|excel)\s*-\s*", re.IGNORECASE)


def _is_generic_title(value: str) -> bool:
    words = re.findall(r"[a-z]+", value.lower())
    return not words or all(word in _GENERIC_TITLE_WORDS for word in words)


def _infer_title(metadata: dict[str, str], file_path: Path) -> str:
    """Titel uit de PDF-metadata, anders de bestandsnaam.

    De eerste tekstregel is bewust géén kandidaat: op een opgavenblad is dat de
    inleverdatum en op een hoofdstukscan de sectiekop. De bestandsnaam beheer je
    zelf via de mapstructuur en is daarmee de voorspelbaarste bron.
    """
    for key in ("Title", "title"):
        value = _OFFICE_PREFIX_RE.sub("", normalize_text(metadata.get(key) or ""))
        if value and not _is_generic_title(value):
            return value

    return title_from_filename(file_path.stem)


def _flatten_outline(items, reader, depth: int = 0) -> list[tuple[int, int, str]]:
    """Maak van de geneste bladwijzerboom een platte lijst (pagina, diepte, titel)."""
    flat: list[tuple[int, int, str]] = []
    for item in items:
        if isinstance(item, list):
            flat.extend(_flatten_outline(item, reader, depth + 1))
            continue
        title = normalize_text(getattr(item, "title", "") or "")
        if not title:
            continue
        try:
            page_index = reader.get_destination_page_number(item)
        except Exception:
            continue
        flat.append((page_index, depth, title))
    return flat


def _outline_paths_by_page(reader, page_count: int) -> dict[int, str]:
    """Koppel elk paginanummer aan het diepste bladwijzerpad dat er geldt.

    De bladwijzers van een PDF zijn de inhoudsopgave zoals de uitgever hem heeft
    vastgelegd: hiërarchisch, met paginanummers, en zonder de giswerk-fouten die
    kopherkenning op geëxtraheerde tekst onvermijdelijk maakt.
    """
    try:
        entries = _flatten_outline(reader.outline, reader)
    except Exception:
        return {}
    if not entries:
        return {}

    entries.sort(key=lambda entry: (entry[0], entry[1]))

    paths: dict[int, str] = {}
    stack: list[str] = []
    cursor = 0
    current: str | None = None

    for page_index in range(page_count):
        while cursor < len(entries) and entries[cursor][0] <= page_index:
            _, depth, title = entries[cursor]
            stack = [*stack[:depth], title]
            current = SECTION_SEPARATOR.join(stack)
            cursor += 1
        if current:
            paths[page_index + 1] = current
    return paths


# Sommige lettertypen (het tentamenplatform Ans gebruikt er zo een) koppelen
# hun cijfers niet aan Unicode. pypdf schrijft dan de glyphnaam uit: `529` wordt
# `/five.pnum/two.pnum/nine.pnum`, en de breuk `1/6` wordt `/one.pnum/6`.
_DIGIT_NAMES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_SUFFIXED_GLYPH_RE = re.compile(r"/(?:%s)\.(?:pnum|tnum|lf|osf)" % "|".join(_DIGIT_NAMES))
# De kale vorm (`/one` zonder achtervoegsel) komt in dezelfde documenten voor,
# maar is op zichzelf te gewoon om blind te vervangen — denk aan een URL.
_GLYPH_RE = re.compile(r"/(%s)(?:\.(?:pnum|tnum|lf|osf)|(?![A-Za-z]))" % "|".join(_DIGIT_NAMES))
# Vanaf hoeveel glyphnamen met achtervoegsel een document als aangetast geldt.
_GLYPH_EVIDENCE = 3


def repair_glyph_names(page_texts: list[str]) -> list[str]:
    """Zet uitgeschreven cijferglyphs terug naar cijfers, per document.

    Alleen als het document zelf laat zien dat zijn lettertype dit doet: pas
    dan wordt ook de kale vorm vervangen. De glyphnaam slikt zijn eigen
    schuine streep, dus een echte breukstreep ernaast blijft staan —
    `6//one.pnum/one.pnum` wordt `6/11`.
    """
    evidence = sum(len(_SUFFIXED_GLYPH_RE.findall(text)) for text in page_texts)
    if evidence < _GLYPH_EVIDENCE:
        return page_texts
    digit = {name: str(index) for index, name in enumerate(_DIGIT_NAMES)}
    return [_GLYPH_RE.sub(lambda match: digit[match.group(1)], text) for text in page_texts]


def parse_pdf(file_path: Path) -> ParsedDocument:
    reader = PdfReader(str(file_path))
    raw_metadata = {str(key).lstrip("/"): str(value) for key, value in dict(reader.metadata or {}).items()}
    page_texts = repair_glyph_names([page.extract_text() or "" for page in reader.pages])
    cleaned = _strip_common_headers_and_footers(page_texts)
    outline_paths = _outline_paths_by_page(reader, len(page_texts))

    pages = [
        ParsedPage(
            page_number=index + 1,
            text=normalize_text(text),
            running_header=header,
            outline_path=outline_paths.get(index + 1),
        )
        for index, (text, header) in enumerate(cleaned)
        if normalize_text(text)
    ]

    title = _infer_title(raw_metadata, file_path)
    return ParsedDocument(
        title=title,
        page_count=len(reader.pages),
        pages=pages,
        metadata=raw_metadata,
    )
