"""Eén slide is één chunk.

Een slide draagt één gedachte; die moet als geheel terugkomen in het bewijs.
Vensters van 425 woorden zouden hier slides aan elkaar plakken die niets met
elkaar te maken hebben.
"""
from __future__ import annotations

import re

from app.services.chunking.common import SECTION_SEPARATOR, ChunkDraft, word_count
from app.services.parsing import ParsedPage, normalize_text, title_from_filename


MIN_SLIDE_WORDS = 25


def deck_title(title: str, filename_stem: str) -> str:
    """De titel waaronder de slides van één college in een sectiepad staan.

    Een slidedeck draagt vaak de titel van het vák in zijn metadata, voor elk
    college dezelfde. Omdat die titel de wortel van het sectiepad is, belandden
    college 3 en 4 dan in één deck, met twee keer "slide 5". Een collegetitel
    zonder enig getal, terwijl de bestandsnaam er wel een heeft, is zo'n
    reekstitel: dan wint de bestandsnaam. "Lecture 3" houdt zijn titel.
    """
    if re.search(r"\d", title) or not re.search(r"\d", filename_stem):
        return title
    return title_from_filename(filename_stem)


def chunk_slides(
    pages: list[ParsedPage],
    *,
    deck_title: str,
    min_words: int = MIN_SLIDE_WORDS,
) -> list[ChunkDraft]:
    if not pages:
        return []

    chunks: list[ChunkDraft] = []

    def emit(group: list[ParsedPage]) -> None:
        text = "\n\n".join(page.text for page in group).strip()
        if not text:
            return
        first, last = group[0].page_number, group[-1].page_number
        label = f"slide {first}" if first == last else f"slides {first}-{last}"
        section_path = f"{deck_title}{SECTION_SEPARATOR}{label}" if deck_title else label
        chunks.append(
            ChunkDraft(
                chunk_index=len(chunks),
                section_path=section_path,
                page_start=first,
                page_end=last,
                token_count=word_count(text),
                text=f"{section_path}\n{text}",
                normalized_text=normalize_text(text.lower()),
                chunk_metadata={
                    "slide_number": first,
                    "slide_span": [first, last],
                    "deck_title": deck_title,
                },
            )
        )

    pending: list[ParsedPage] = []
    for page in pages:
        pending.append(page)
        if word_count("\n".join(item.text for item in pending)) >= min_words:
            emit(pending)
            pending = []

    # Een korte laatste slide heeft geen opvolger om bij aan te schuiven; die
    # wordt alsnog een eigen chunk in plaats van weggegooid.
    if pending:
        emit(pending)

    return chunks
