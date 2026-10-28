"""Wat hoort er bij een week.

Slides en opgaven dragen hun week in het pad, maar een boek hoort bij het hele
vak. Zonder deze koppeling bereikt een weekfilter dus alleen de slides — en
dan gaat "vat week 3 samen" over twee collegedecks terwijl de helft van de
stof in het boek staat.

Het weekplan uit `course.yml` noemt hoofdstukken; hier worden die vertaald
naar concrete paginabereiken, want dat is wat beide retrievaltakken kunnen
filteren. De vertaling gebeurt per vraag: sectiepaden veranderen bij een
herindexering, paginanummers in de database niet meer dan het boek zelf.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Chunk, Course, Document


SECTION_SEPARATOR = " › "


@dataclass(frozen=True)
class PageSpan:
    """Een stuk van één document dat bij een week hoort."""

    document_id: str
    page_start: int
    page_end: int


@dataclass
class WeekScope:
    """Alles wat bij een week hoort: eigen documenten plus stukken uit boeken."""

    week: int
    topics: list[str] = field(default_factory=list)
    lectures: list[int] = field(default_factory=list)
    spans: list[PageSpan] = field(default_factory=list)
    # Leesregels die nergens op uitkwamen: een verkeerd pad of een sectie die
    # niet bestaat. Zichtbaar maken in plaats van stil niets opleveren.
    unresolved: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.spans


def _segments_match(section_path: str | None, prefixes: list[str]) -> bool:
    """Matcht als één segment van het pad met een van de prefixen begint.

    Zo hoef je in course.yml alleen "9.2" te schrijven en niet het hele
    `9 Inferences from One Sample › 9.2 Two Proportions`. Het werkt ook als
    een andere uitgever de nummering anders nest.
    """
    if not section_path:
        return False
    segments = [segment.strip().lower() for segment in section_path.split(SECTION_SEPARATOR.strip())]
    return any(segment.startswith(prefix.lower()) for segment in segments for prefix in prefixes)


def _spans_for_reading(db: Session, course_slug: str, item: dict) -> tuple[list[PageSpan], str | None]:
    document = db.scalar(
        select(Document).where(
            Document.course_slug == course_slug,
            Document.source_path == item["document"],
            Document.ingestion_status == "indexed",
        )
    )
    if document is None:
        return [], f"{item['document']} staat niet (geïndexeerd) in {course_slug}"

    pages = item.get("pages")
    if pages:
        return [PageSpan(document.id, int(pages[0]), int(pages[1]))], None

    sections = item.get("sections") or []
    if not sections:
        # Geen sectie en geen pagina's: het hele document hoort bij deze week.
        bounds = db.execute(
            select(func.min(Chunk.page_start), func.max(Chunk.page_end)).where(
                Chunk.document_id == document.id
            )
        ).one()
        if bounds[0] is None:
            return [], f"{item['document']} heeft geen chunks"
        return [PageSpan(document.id, int(bounds[0]), int(bounds[1]))], None

    rows = db.execute(
        select(Chunk.section_path, func.min(Chunk.page_start), func.max(Chunk.page_end))
        .where(Chunk.document_id == document.id, Chunk.section_path.is_not(None))
        .group_by(Chunk.section_path)
    ).all()

    spans = [
        PageSpan(document.id, int(page_start), int(page_end))
        for section_path, page_start, page_end in rows
        if _segments_match(section_path, sections)
    ]
    if not spans:
        return [], f"{item['document']}: geen sectie begint met {', '.join(sections)}"
    return spans, None


def week_scope(db: Session, course_slug: str, week: int) -> WeekScope:
    course = db.get(Course, course_slug)
    plan = ((course.week_plans if course else None) or {}).get(str(week)) or {}

    scope = WeekScope(
        week=week,
        topics=list(plan.get("topics") or []),
        lectures=list(plan.get("lectures") or []),
    )
    for item in plan.get("reading") or []:
        spans, problem = _spans_for_reading(db, course_slug, item)
        scope.spans.extend(spans)
        if problem:
            scope.unresolved.append(problem)
    return scope
