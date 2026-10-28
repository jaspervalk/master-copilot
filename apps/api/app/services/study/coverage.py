"""Per week: wat er ligt, wat je ervan kent, en wat er ontbreekt.

Dit overzicht is de ruggengraat van de oefenpagina. Het telt alleen wat
vaststaat. Een onderwerp geldt als gedekt wanneer een kaart bij het maken aan
dat onderwerp is gehangen — niet wanneer een zoekactie het onderwerp ergens
terugvindt. Raden zou hier een gerust gevoel geven over stof die je nooit hebt
geoefend.

Eén nuance, en die is nodig. Kaarten uit een tentamentranscriptie dragen het
onderwerp zoals dat tentamen het noemt ("numpy broadcasting"), en je
studiewijzer noemt hetzelfde anders ("numpy"). Letterlijk vergelijken meldde
daardoor bij FDS dat er geen kaarten waren terwijl er honderd stonden. Een
kaart dekt een onderwerp daarom ook als de onderscheidende woorden ervan in
zijn eigen label staan — dezelfde toets als bij de oefententamens. "Statistical
Learning — Supervised Learning" dekt zo nog steeds geen "naive bayes".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Chunk, Course, Document, WeekSummary, utcnow
from app.services.practice.practice_exams import covers
from app.services.study.mastery import BEHEERST, LEREND, NIEUW, ZWAK, CardState, card_states
from app.services.weeks_summary import is_stale


@dataclass
class WeekCoverage:
    week: int
    lectures: list[int] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    # Hoeveel stukken tekst er van deze week in het corpus zitten. Nul betekent:
    # er valt nog niets te oefenen, hoe graag de studiewijzer het ook wil.
    material_chunks: int = 0
    cards: int = 0
    new: int = 0
    learning: int = 0
    mastered: int = 0
    weak: int = 0
    due: int = 0
    topics_without_cards: list[str] = field(default_factory=list)
    has_summary: bool = False
    summary_stale: bool = False
    last_practised: datetime | None = None

    @property
    def practised(self) -> int:
        """Kaarten die je minstens één keer deed."""
        return self.cards - self.new

    @property
    def mastered_share(self) -> float:
        return self.mastered / self.cards if self.cards else 0.0


def _material_per_week(db: Session, course_slug: str) -> dict[int, int]:
    rows = db.execute(
        select(Document.week, func.count(Chunk.id))
        .join(Chunk, Chunk.document_id == Document.id)
        .where(
            Document.course_slug == course_slug,
            Document.ingestion_status == "indexed",
            Document.week.is_not(None),
        )
        .group_by(Document.week)
    ).all()
    return {week: count for week, count in rows}


def _plans(db: Session, course_slug: str) -> dict[int, dict]:
    course = db.get(Course, course_slug)
    if course is None:
        return {}
    plans: dict[int, dict] = {}
    for key, plan in (course.week_plans or {}).items():
        try:
            plans[int(key)] = plan or {}
        except (TypeError, ValueError):
            # Een onleesbare sleutel is al gemeld door parse_course_config.
            continue
    return plans


def week_coverage(
    db: Session,
    course_slug: str,
    *,
    now: datetime | None = None,
    states: list[CardState] | None = None,
) -> list[WeekCoverage]:
    """Eén regel per week die bestaat: in de studiewijzer, in het corpus, of in
    je kaarten."""
    now = now or utcnow()
    states = card_states(db, course_slug, now=now) if states is None else states

    plans = _plans(db, course_slug)
    material = _material_per_week(db, course_slug)
    summaries = {
        summary.week: summary
        for summary in db.scalars(select(WeekSummary).where(WeekSummary.course_slug == course_slug))
    }

    weeks = set(plans) | set(material) | {state.week for state in states if state.week is not None}

    coverage: list[WeekCoverage] = []
    for week in sorted(weeks):
        plan = plans.get(week, {})
        eigen = [state for state in states if state.week == week]
        labels = {state.topic for state in eigen if state.topic}
        topics = list(plan.get("topics") or [])
        summary = summaries.get(week)
        laatste = [state.last_at for state in eigen if state.last_at is not None]

        coverage.append(
            WeekCoverage(
                week=week,
                lectures=list(plan.get("lectures") or []),
                topics=topics,
                material_chunks=material.get(week, 0),
                cards=len(eigen),
                new=sum(1 for state in eigen if state.state == NIEUW),
                learning=sum(1 for state in eigen if state.state == LEREND),
                mastered=sum(1 for state in eigen if state.state == BEHEERST),
                weak=sum(1 for state in eigen if state.state == ZWAK),
                due=sum(1 for state in eigen if state.due_at <= now),
                topics_without_cards=[
                    topic
                    for topic in topics
                    if topic not in labels and not any(covers(label, topic) for label in labels)
                ],
                has_summary=summary is not None,
                summary_stale=summary is not None and is_stale(db, summary),
                last_practised=max(laatste) if laatste else None,
            )
        )
    return coverage
