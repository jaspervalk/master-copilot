"""Welke uitwerkingen moeten verborgen blijven.

Een `solution` of `submission` uit een week waarin een beoordeelde opdracht
nog open staat is een spoiler. Oefenmateriaal (`exercise`) telt niet mee:
nakijken hoort bij oefenen. Dit staat altijd aan, ook zonder coachmodus — het
verbergen van een uitwerking mag niet van een schakelaar afhangen.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document


HiddenWeeks = dict[str, set[int]]
HIDDEN_KINDS = ("solution", "submission")


def open_assignment_weeks(db: Session) -> HiddenWeeks:
    stmt = select(Document.course_slug, Document.week).where(
        Document.doc_kind == "assignment",
        Document.assignment_status == "open",
        Document.week.is_not(None),
    )
    hidden: HiddenWeeks = {}
    for course_slug, week in db.execute(stmt):
        hidden.setdefault(course_slug, set()).add(int(week))
    return hidden


def is_hidden(course_slug: str, doc_kind: str, week: int | None, hidden: HiddenWeeks | None) -> bool:
    if not hidden or doc_kind not in HIDDEN_KINDS or week is None:
        return False
    return week in hidden.get(course_slug, ())
