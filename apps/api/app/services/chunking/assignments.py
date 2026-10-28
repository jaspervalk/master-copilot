"""Knip opgavenbladen en uitwerkingen op opgave-eenheden.

Een opgave en zijn uitwerking horen in één chunk: haal je ze uit elkaar, dan
krijg je bij het studeren een antwoord zonder vraag of andersom.
"""
from __future__ import annotations

import re

from app.services.chunking.common import OVERLAP_WORDS, TARGET_WORDS, ChunkDraft, tokens, word_count
from app.services.parsing import ParsedPage, normalize_text, split_code_blocks


_EXERCISE_RE = re.compile(
    r"^\s*(exercise|opgave|vraag|question|problem|oefening)\s*([0-9]+[a-z]?|[ivxl]+)\b[.:]?\s*$",
    re.IGNORECASE,
)


Group = tuple[str | None, str | None, list[tuple[str, int]]]


def _sections(pages: list[ParsedPage]) -> list[Group]:
    """Groepeer regels per opgave. Elke groep: (sectiepad, kopregel, [(regel, paginanummer)])."""
    groups: list[Group] = [(None, None, [])]
    for page in pages:
        for is_code, segment in split_code_blocks(page.text):
            if is_code:
                # Heel laten; `tokens` herkent hem aan het regeleinde.
                groups[-1][2].append((segment, page.page_number))
                continue
            for raw_line in segment.splitlines():
                line = normalize_text(raw_line)
                if not line:
                    continue
                if _EXERCISE_RE.match(line):
                    groups.append((line, line, []))
                    continue
                groups[-1][2].append((line, page.page_number))
    return [group for group in groups if group[2]]


def _outline_sections(pages: list[ParsedPage]) -> list[Group]:
    """Eén groep per pagina met een kopjespad: de kop is de eerste regel, het
    pad de sectie. Voor markdown, dat al per kop in pagina's is opgeknipt."""
    groups: list[Group] = []
    for page in pages:
        lines: list[str] = []
        for is_code, segment in split_code_blocks(page.text):
            if is_code:
                lines.append(segment)
            else:
                lines.extend(line for raw in segment.splitlines() if (line := normalize_text(raw)))
        # De kop is de eerste regel proza, nooit een codeblok.
        if page.outline_path is not None and lines and "\n" not in lines[0]:
            heading, lines = lines[0], lines[1:]
        else:
            heading = None
        if lines:
            groups.append((page.outline_path, heading, [(line, page.page_number) for line in lines]))
    return groups


def chunk_assignment(
    pages: list[ParsedPage],
    *,
    target_words: int = TARGET_WORDS,
    overlap_words: int = OVERLAP_WORDS,
    by_outline: bool = False,
) -> list[ChunkDraft]:
    groups = _outline_sections(pages) if by_outline else _sections(pages)
    if not groups:
        return []

    chunks: list[ChunkDraft] = []
    for section_path, heading, lines in groups:
        words: list[str] = []
        word_pages: list[int] = []
        for line, page_number in lines:
            line_words = tokens(line)
            words.extend(line_words)
            word_pages.extend([page_number] * len(line_words))
        if not words:
            continue

        start = 0
        while start < len(words):
            stop = min(len(words), start + target_words)
            snippet = " ".join(words[start:stop]).strip()
            text = f"{heading}\n{snippet}".strip() if heading else snippet
            window_pages = word_pages[start:stop]
            page_start = min(window_pages)
            page_end = max(window_pages)
            chunks.append(
                ChunkDraft(
                    chunk_index=len(chunks),
                    section_path=section_path,
                    page_start=page_start,
                    page_end=page_end,
                    token_count=word_count(text),
                    text=text,
                    normalized_text=normalize_text(text.lower()),
                    chunk_metadata={"exercise": section_path, "page_span": [page_start, page_end]},
                )
            )
            if stop >= len(words):
                break
            start = max(0, stop - overlap_words)

    return chunks
