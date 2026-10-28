from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Course, Document
from app.schemas import CourseRead


router = APIRouter()


@router.get("/courses", response_model=list[CourseRead])
def get_courses(db: Annotated[Session, Depends(get_db)]) -> list[CourseRead]:
    documents = list(db.scalars(select(Document)))
    courses = {course.slug: course for course in db.scalars(select(Course))}

    summaries: dict[str, dict] = {}
    for document in documents:
        entry = summaries.setdefault(
            document.course_slug,
            {"document_count": 0, "weeks": set(), "open_assignment_count": 0},
        )
        entry["document_count"] += 1
        if document.week is not None:
            entry["weeks"].add(document.week)
        if document.doc_kind == "assignment" and document.assignment_status == "open":
            entry["open_assignment_count"] += 1

    result: list[CourseRead] = []
    for slug, entry in sorted(summaries.items()):
        course = courses.get(slug)
        result.append(
            CourseRead(
                slug=slug,
                name=course.name if course else slug.replace("-", " ").title(),
                period=course.period if course else None,
                lecturer=course.lecturer if course else None,
                document_count=entry["document_count"],
                weeks=sorted(entry["weeks"]),
                open_assignment_count=entry["open_assignment_count"],
            )
        )
    return result
