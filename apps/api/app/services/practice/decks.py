"""Decks zijn sectiepaden.

Een deck komt rechtstreeks uit SQL, niet uit retrieval: we willen niet de
semantisch beste fragmenten maar *alle* tekst van één sectie, want dat is de
eenheid waarin het boek zelf is ingedeeld. Dat scheelt ook een embedding en de
Qdrant-lock.

Een deck mag ook een bovenliggend pad zijn. Slides leveren één sectie per
slide op; zonder "Lecture 3" als deck valt een heel college buiten de lijst en
kun je alleen per losse slide oefenen.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Chunk, Document, PracticeCard


SEPARATOR = " › "

# Genoeg tekst om vragen uit te maken zonder de prompt te laten ontploffen.
# Het budget staat in tekens, niet in chunks: een boekchunk is een halve
# pagina en een slide twee zinnen, dus een vast aantal chunks zou het ene
# deck uithongeren en het andere laten overlopen.
MAX_SOURCE_CHARS = 24_000
MAX_SOURCE_CHUNKS = 60

# Een bovenliggend pad wordt pas een deck als het meerdere secties bundelt;
# anders krijg je van elke sectie een tweede, identiek deck.
MIN_CHILDREN_FOR_PARENT = 2


@dataclass
class DeckSummary:
    section_path: str
    document_title: str
    page_start: int
    page_end: int
    chunk_count: int
    card_count: int


def _prefix_clause(section_path: str):
    """Deze sectie plus alles eronder.

    De scheiding wordt meegenomen in de LIKE, zodat "Lecture 3" niet ook
    "Lecture 30" opslokt.
    """
    return or_(
        Chunk.section_path == section_path,
        Chunk.section_path.like(f"{section_path}{SEPARATOR}%"),
    )


def section_chunks(db: Session, course_slug: str, section_path: str) -> list[Chunk]:
    """De tekst van één deck, in leesvolgorde, afgekapt op het tekenbudget."""
    stmt = (
        select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .where(
            Document.course_slug == course_slug,
            Document.ingestion_status == "indexed",
            _prefix_clause(section_path),
        )
        .order_by(Chunk.document_id, Chunk.chunk_index)
        .limit(MAX_SOURCE_CHUNKS)
    )

    chunks: list[Chunk] = []
    budget = MAX_SOURCE_CHARS
    for chunk in db.scalars(stmt):
        # Altijd minstens één chunk: een enkele lange sectie levert anders niets.
        if chunks and len(chunk.text) > budget:
            break
        chunks.append(chunk)
        budget -= len(chunk.text)
    return chunks


def _parents(section_path: str) -> list[str]:
    parts = section_path.split(SEPARATOR)
    return [SEPARATOR.join(parts[:depth]) for depth in range(1, len(parts))]


def list_decks(db: Session, course_slug: str, *, min_chunks: int = 1) -> list[DeckSummary]:
    """Sectiepaden van dit vak, met hoeveel tekst en hoeveel kaarten er al zijn."""
    sections = db.execute(
        select(
            Chunk.section_path,
            func.min(Document.title),
            func.min(Chunk.page_start),
            func.max(Chunk.page_end),
            func.count(Chunk.id),
        )
        .join(Document, Chunk.document_id == Document.id)
        .where(
            Document.course_slug == course_slug,
            Document.ingestion_status == "indexed",
            Chunk.section_path.is_not(None),
        )
        .group_by(Chunk.section_path)
        .order_by(Chunk.section_path)
    ).all()

    # (titel, eerste pagina, laatste pagina, chunks, aantal eigen subsecties)
    totals: dict[str, list] = {}
    for section_path, title, page_start, page_end, chunk_count in sections:
        totals[section_path] = [title, page_start, page_end, chunk_count, 0]
    for section_path, title, page_start, page_end, chunk_count in sections:
        for parent in _parents(section_path):
            entry = totals.get(parent)
            if entry is None:
                entry = totals[parent] = [title, page_start, page_end, 0, 0]
            entry[1] = min(entry[1], page_start)
            entry[2] = max(entry[2], page_end)
            entry[3] += chunk_count
            entry[4] += 1

    card_counts = dict(
        db.execute(
            select(PracticeCard.section_path, func.count(PracticeCard.id))
            .where(PracticeCard.course_slug == course_slug, PracticeCard.disabled.is_(False))
            .group_by(PracticeCard.section_path)
        ).all()
    )

    decks = [
        DeckSummary(
            section_path=section_path,
            document_title=title,
            page_start=page_start,
            page_end=page_end,
            chunk_count=chunk_count,
            card_count=card_counts.get(section_path, 0),
        )
        for section_path, (title, page_start, page_end, chunk_count, children) in totals.items()
        if chunk_count >= min_chunks and (children == 0 or children >= MIN_CHILDREN_FOR_PARENT)
    ]
    decks.sort(key=lambda deck: deck.section_path)
    return decks


def deck_cards(db: Session, course_slug: str, section_path: str) -> list[PracticeCard]:
    stmt = (
        select(PracticeCard)
        .where(
            PracticeCard.course_slug == course_slug,
            PracticeCard.section_path == section_path,
            PracticeCard.disabled.is_(False),
        )
        .order_by(PracticeCard.created_at, PracticeCard.id)
    )
    return list(db.scalars(stmt))
