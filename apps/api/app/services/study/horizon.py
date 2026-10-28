"""Hoeveel tijd is er nog, en wat betekent dat voor de herhaling.

De ladder in `practice/scheduling.py` is gemaakt om iets jarenlang te
onthouden: na vier goede antwoorden komt een kaart pas over 35 dagen terug. Met
nog vier weken tot het tentamen is dat precies één keer te weinig.

Cepeda e.a. (2008) maten hoe de beste tussenpoos samenhangt met hoe lang je het
moet onthouden: ongeveer een tiende tot een vijfde van die periode. Vandaar één
regel: een kaart blijft nooit langer weg dan een vijfde van de tijd tot je
tentamen, en in de laatste dagen komt alles nog een keer langs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CanvasItem, Course, utcnow
# Doorgeefluik: de fractie hoort bij de ladder, en die staat in scheduling.
from app.services.practice.scheduling import HORIZON_SHARE  # noqa: F401


@dataclass(frozen=True)
class Exam:
    name: str
    day: date
    days_left: int
    source: str  # "course.yml" of "canvas"


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


def next_exam(db: Session, course_slug: str, *, now: datetime | None = None) -> Exam | None:
    """Het eerstvolgende tentamen van dit vak, uit course.yml of uit Canvas.

    De agenda meldt het al wanneer die twee uiteenlopen; hier telt gewoon de
    vroegste, want de horizon moet de krapste zijn.
    """
    now = now or utcnow()
    today = now.date()

    course = db.get(Course, course_slug)
    if course is None:
        return None

    kandidaten: list[Exam] = []
    for entry in course.exams or []:
        day = _as_date((entry or {}).get("date"))
        if day is not None and day >= today:
            kandidaten.append(
                Exam(name=str(entry.get("name") or "Tentamen"), day=day, days_left=(day - today).days, source="course.yml")
            )

    if course.canvas_id is not None:
        rows = db.scalars(
            select(CanvasItem).where(
                CanvasItem.canvas_course_id == course.canvas_id,
                CanvasItem.kind == "exam",
                CanvasItem.due_at.is_not(None),
            )
        )
        for item in rows:
            day = _as_date(item.due_at)
            if day is not None and day >= today:
                kandidaten.append(Exam(name=item.title, day=day, days_left=(day - today).days, source="canvas"))

    if not kandidaten:
        return None
    return min(kandidaten, key=lambda exam: (exam.day, exam.source))


def horizon_days(db: Session, course_slug: str, *, now: datetime | None = None) -> int | None:
    exam = next_exam(db, course_slug, now=now)
    return None if exam is None else exam.days_left
