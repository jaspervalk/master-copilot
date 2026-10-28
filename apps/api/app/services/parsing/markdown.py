"""Markdown: eigen aantekeningen, en opgaven die alleen als tekst in Canvas
staan.

Een markdownbestand heeft geen pagina's; de koppen zijn de structuur. Elke
kop van niveau 1 tot en met 3 begint een nieuwe 'pagina' met het kopjespad als
`outline_path`, zoals de bladwijzers van een PDF. De chunkers hoeven er zo
niets van te weten: proza gebruikt dat pad als sectie, en een opgavenblad
knipt per kop (zie `chunk_document`).
"""
from __future__ import annotations

import re
from pathlib import Path

from app.services.parsing import ParsedDocument, ParsedPage, normalize_text, title_from_filename


# Dezelfde scheiding als de chunkers gebruiken voor sectiepaden.
_SEPARATOR = " › "
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# Commentaar is voor wie het bestand bewerkt ("antwoord: nog niet
# vrijgegeven"), niet voor wie het doorzoekt.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def parse_markdown(file_path: Path) -> ParsedDocument:
    return parse_markdown_text(file_path.read_text(encoding="utf-8"), stem=file_path.stem)


def parse_markdown_text(text: str, *, stem: str, source_format: str = "markdown") -> ParsedDocument:
    """Dezelfde indeling voor tekst die niet uit een .md-bestand komt.

    Een notebook wordt eerst markdown en gaat dan hierdoorheen; zo is er één
    plek waar koppen een kopjespad worden.
    """
    text = _COMMENT_RE.sub("", text)

    title: str | None = None
    stack: list[tuple[int, str]] = []
    # (kopjespad of None voor wat vóór de eerste kop staat, regels)
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            sections[-1][1].append(line)
            continue
        # Een # in een codeblok is commentaar in Python, geen kop.
        match = None if in_fence else _HEADING_RE.match(line)
        if match is None:
            sections[-1][1].append(line)
            continue
        level, heading = len(match.group(1)), match.group(2).strip()
        if level == 1 and title is None:
            title = heading
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading))
        # De kop zelf is de eerste regel van zijn pagina, zonder hekjes.
        sections.append((_SEPARATOR.join(part for _, part in stack), [heading]))

    pages: list[ParsedPage] = []
    for outline, lines in sections:
        body = [line for line in lines if line.strip()]
        # Een kop zonder eigen tekst ("## Vraag 2" direct gevolgd door
        # "### Deel a") is geen pagina; zijn naam zit in het pad van de volgende.
        if not body or (outline is not None and len(body) == 1):
            continue
        pages.append(
            ParsedPage(page_number=len(pages) + 1, text=normalize_text("\n".join(lines)), outline_path=outline)
        )

    return ParsedDocument(
        title=title or title_from_filename(stem),
        page_count=len(pages),
        pages=pages,
        metadata={"source_format": source_format},
    )
