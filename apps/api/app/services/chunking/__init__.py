"""Kies de chunkstrategie op basis van het documentsoort."""
from __future__ import annotations

from app.services.chunking.assignments import chunk_assignment
from app.services.chunking.common import (
    OVERLAP_WORDS,
    SECTION_SEPARATOR,
    TARGET_WORDS,
    ChunkDraft,
)
from app.services.chunking.prose import chunk_prose
from app.services.chunking.slides import chunk_slides
from app.services.parsing import ParsedDocument


_PROSE_KINDS = {"book", "paper", "note"}
# Een tentamen is net als een opgavenblad per vraag opgebouwd.
_EXERCISE_KINDS = {"assignment", "exercise", "submission", "solution", "exam"}

__all__ = [
    "ChunkDraft",
    "OVERLAP_WORDS",
    "SECTION_SEPARATOR",
    "TARGET_WORDS",
    "chunk_document",
]


def chunk_document(*, doc_kind: str, parsed: ParsedDocument) -> list[ChunkDraft]:
    if doc_kind == "slides":
        return chunk_slides(parsed.pages, deck_title=parsed.title)
    if doc_kind in _EXERCISE_KINDS:
        # Markdown is al per kop opgeknipt, en "Vraag 1 — één antwoord · 1 punt"
        # is geen kale "Vraag 1" die de regelherkenning oppikt.
        # Een notebook is markdown in een andere verpakking: ook daar staat elke
        # opgave onder zijn eigen kop.
        return chunk_assignment(
            parsed.pages, by_outline=parsed.metadata.get("source_format") in ("markdown", "notebook", "script")
        )
    if doc_kind in _PROSE_KINDS:
        return chunk_prose(parsed.pages)
    raise ValueError(f"Geen chunkstrategie voor documentsoort '{doc_kind}'")
