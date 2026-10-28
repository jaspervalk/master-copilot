"""Drie getallen voor de navigatiebalk: wat vraagt er nu aandacht?

Bewust klein gehouden. Dit draait bij elke paginawissel, dus er komt geen
Canvas aan te pas en er wordt geen leesmodel opgebouwd — alleen tellen.

Wat hier níet gebeurt is de status opnieuw uitrekenen. `derive_status` en
`bucket_for` uit de agenda zijn de enige plek waar staat wanneer iets open is
of te laat; een tweede versie ervan zou stilletjes uit de pas kunnen lopen, en
dan zegt de balk iets anders dan de pagina waar hij naartoe wijst.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CanvasCourse, CanvasItem, Course, Task, utcnow
from app.services.canvas.agenda import FINISHED, bucket_for, derive_status
from app.services.practice.scheduling import due_cards
from app.services.study.horizon import horizon_days


@dataclass(frozen=True)
class Attention:
    # Deadlines en taken van vandaag die nog niet af zijn.
    today: int
    # Datums die al verstreken zijn en nog openstaan.
    overdue: int
    # Oefenkaarten die nu aan de beurt zijn, over alle vakken.
    due_cards: int


def _as_date(value) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def attention(db: Session, *, now: datetime | None = None) -> Attention:
    now = now or utcnow()

    verborgen = {
        canvas_id
        for (canvas_id,) in db.execute(select(CanvasCourse.id).where(CanvasCourse.hidden.is_(True)))
    }

    today = overdue = 0

    for item in db.scalars(select(CanvasItem).where(CanvasItem.due_at.is_not(None))):
        if item.canvas_course_id in verborgen:
            continue
        # FINISHED, niet SETTLED: `done` vraagt niets meer van je, ook al is het
        # vinkje nog terug te draaien. De agenda maakt datzelfde onderscheid.
        status = derive_status(item, now)
        if status in FINISHED:
            continue
        bucket = bucket_for(item.due_at, now=now, finished=False)
        if bucket == "today":
            today += 1
        elif bucket == "overdue":
            overdue += 1

    verborgen_vakken = set(db.scalars(select(Course.slug).where(Course.canvas_id.in_(verborgen)))) if verborgen else set()
    for task in db.scalars(select(Task).where(Task.done_at.is_(None), Task.deleted_at.is_(None))):
        if task.course_slug in verborgen_vakken:
            continue
        bucket = bucket_for(_as_date(task.due_on), now=now, finished=False)
        if bucket == "today":
            today += 1
        elif bucket == "overdue":
            overdue += 1

    # Per vak, want de herhaalafstand hangt af van de tentamendatum van dát vak.
    # Een verborgen vak doe je niet meer: zijn kaarten wachten niet op je.
    klaar = 0
    for slug in db.scalars(select(Course.slug)):
        if slug in verborgen_vakken:
            continue
        klaar += len(due_cards(db, slug, now=now, horizon_days=horizon_days(db, slug, now=now)))

    return Attention(today=today, overdue=overdue, due_cards=klaar)
