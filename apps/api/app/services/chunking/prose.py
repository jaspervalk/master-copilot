"""Vensterchunker voor doorlopende tekst: boeken, papers, aantekeningen."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.chunking.common import (
    OVERLAP_WORDS,
    TARGET_WORDS,
    ChunkDraft,
    join_sections,
    looks_like_heading,
    push_heading,
    tokens,
    word_count,
)
from app.services.parsing import ParsedPage, normalize_text, split_code_blocks


@dataclass
class _Block:
    section_path: str | None
    text: str
    page_number: int


def _split_blocks(pages: list[ParsedPage]) -> list[_Block]:
    """Splits de tekst in alinea's en houdt daarbij de koppenstapel bij.

    De kopherkenning kijkt per regel, niet per alinea. PDF-extractie levert
    lang niet altijd lege regels tussen alinea's; deed hij dat wel, dan zou een
    kop midden in een blok verdwijnen en zouden alle chunks van een hoofdstuk
    zonder vindplaats eindigen.
    """
    blocks: list[_Block] = []
    stack: list[str] = []
    # Heeft dit document bladwijzers, dan is elke gok op basis van de tekst
    # alleen maar slechter. De kopherkenning gaat dan helemaal uit: een valse
    # kop knipt de tekst én zet er een onzinnige vindplaats boven.
    has_outline = any(page.outline_path for page in pages)

    for page in pages:
        pending: list[str] = []

        def flush_pending() -> None:
            if not pending:
                return
            text = normalize_text(" ".join(pending))
            if text:
                # Volgorde van betrouwbaarheid: de bladwijzers van de uitgever,
                # dan een kop die we in de tekst herkenden, dan de herhaalde
                # kopregel van de pagina.
                section = page.outline_path or join_sections(stack) or page.running_header
                blocks.append(
                    _Block(section_path=section, text=text, page_number=page.page_number)
                )
            pending.clear()

        for is_code, segment in split_code_blocks(page.text):
            if is_code:
                # Een codeblok is één blok, woordelijk: geen kopherkenning op
                # een Python-commentaar, en geen normalisatie die de
                # inspringing plet.
                flush_pending()
                section = page.outline_path or join_sections(stack) or page.running_header
                blocks.append(_Block(section_path=section, text=segment, page_number=page.page_number))
                continue
            for raw_line in re.split(r"\n", segment):
                line = normalize_text(raw_line)
                if not line:
                    flush_pending()
                    continue
                if not has_outline and looks_like_heading(line):
                    flush_pending()
                    stack = push_heading(stack, line)
                    continue
                pending.append(line)
            flush_pending()

        flush_pending()

    return blocks


# Een sectiegrens is de mooiste plek om te knippen, maar alleen als de chunk al
# genoeg body heeft. Knippen bij élke tussenkop leverde fragmenten van veertig
# woorden op: te weinig context om een vraag mee te beantwoorden, en een
# embedding die nergens specifiek op lijkt.
SECTION_BREAK_RATIO = 0.6


def chunk_prose(
    pages: list[ParsedPage],
    *,
    target_words: int = TARGET_WORDS,
    overlap_words: int = OVERLAP_WORDS,
) -> list[ChunkDraft]:
    blocks = _split_blocks(pages)
    if not blocks:
        return []

    overlap = min(overlap_words, max(0, target_words - 1))
    minimum_before_break = int(target_words * SECTION_BREAK_RATIO)

    chunks: list[ChunkDraft] = []
    # Woorden én hun paginanummers parallel bijhouden, zodat de paginaspan van
    # een chunk volgt uit de woorden die er écht in zitten.
    words: list[str] = []
    word_pages: list[int] = []
    section: str | None = blocks[0].section_path
    covered: list[str] = []

    def emit(count: int) -> None:
        """Schrijf de eerste `count` woorden weg als chunk."""
        nonlocal words, word_pages, covered
        snippet = " ".join(words[:count]).strip()
        if not snippet:
            words, word_pages = words[count:], word_pages[count:]
            return
        text = f"{section}\n{snippet}".strip() if section else snippet
        window_pages = word_pages[:count]
        page_start, page_end = min(window_pages), max(window_pages)
        chunks.append(
            ChunkDraft(
                chunk_index=len(chunks),
                section_path=section,
                page_start=page_start,
                page_end=page_end,
                token_count=word_count(text),
                text=text,
                normalized_text=normalize_text(text.lower()),
                chunk_metadata={
                    "section_path": section,
                    # Een chunk kan over een tussenkop heen lopen. `section_path`
                    # is waar hij begint; deze lijst is waar hij doorheen komt,
                    # zodat een citaat de juiste subsectie kan noemen.
                    "sections": list(covered),
                    "page_span": [page_start, page_end],
                },
            )
        )
        words, word_pages = words[count:], word_pages[count:]
        covered = [section] if section else []

    # Hoeveel van de woorden vooraan al in de vorige chunk stonden. Zonder deze
    # telling levert een document dat precies op een chunkgrens eindigt nog een
    # laatste chunk op die enkel uit overlap bestaat.
    carried = 0

    for block in blocks:
        if not words:
            # De chunk begint hier, dus dit is zijn vindplaats.
            section = block.section_path
            carried = 0
        elif block.section_path != section and len(words) >= minimum_before_break:
            emit(len(words))
            section = block.section_path
            carried = 0

        if block.section_path and block.section_path not in covered:
            covered.append(block.section_path)

        block_words = tokens(block.text)
        words.extend(block_words)
        word_pages.extend([block.page_number] * len(block_words))

        while len(words) >= target_words:
            # De staart van déze chunk is de aanloop van de volgende, zodat een
            # zin op de grens niet halveert. Hij wordt vóór het wegschrijven
            # apart gezet: `emit` gooit de weggeschreven woorden weg.
            tail_words = words[target_words - overlap : target_words]
            tail_pages = word_pages[target_words - overlap : target_words]
            emit(target_words)
            words = tail_words + words
            word_pages = tail_pages + word_pages
            carried = len(tail_words)

    if len(words) > carried:
        emit(len(words))

    return chunks
