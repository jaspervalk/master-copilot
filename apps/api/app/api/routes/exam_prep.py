"""De tab Tentamen: één samengesteld antwoord per vak, zoals de agenda en de
studeerpagina. Opbouw, je punten per groep, de oefententamens en de analyse
uit `exams/voorbereiding.yml` komen in één keer, zodat de blokken niet uit de
pas kunnen lopen."""
from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Course
from app.schemas import (
    ExamFactsRead,
    ExamPrepRead,
    ExamSetRead,
    GroupStandingRead,
    PrepPatternRead,
    PrepPlanStepRead,
    PrepRuleRead,
    PrepPracticeRead,
    PrepPredictionRead,
    PrepScenarioRead,
    PrepSourceRead,
    PrepTacticRead,
    StudyExamRead,
)
from app.services.study.exam_prep import ScenarioRow, SourceCheck, build_exam_prep


router = APIRouter(prefix="/exam-prep", tags=["exam-prep"])


def _sources(checks: list[SourceCheck]) -> list[PrepSourceRead]:
    return [
        PrepSourceRead(label=check.label, quote=check.source.quote, found=check.found, reason=check.reason, href=check.href)
        for check in checks
    ]


def _practice(rows: list[ScenarioRow]) -> PrepPracticeRead | None:
    # Eén sectie per patroon, dus de eerste rij zegt waar ze allemaal staan.
    return PrepPracticeRead(origin=rows[0].origin, section=rows[0].section_number) if rows else None


@router.get("", response_model=ExamPrepRead)
def read_exam_prep(course_slug: Annotated[str, Query(min_length=1)], db: Session = Depends(get_db)) -> ExamPrepRead:
    if db.get(Course, course_slug) is None:
        raise HTTPException(status_code=404, detail=f"Onbekend vak: {course_slug}")
    prep = build_exam_prep(db, course_slug)
    return ExamPrepRead(
        course_slug=prep.course_slug,
        has_file=prep.has_file,
        exam=StudyExamRead(name=prep.exam.name, date=prep.exam.day, days_left=prep.exam.days_left, source=prep.exam.source)
        if prep.exam is not None else None,
        facts=ExamFactsRead(**prep.facts.model_dump()) if prep.facts is not None else None,
        total_points=prep.total_points,
        minutes_per_point=prep.minutes_per_point,
        groups=[
            GroupStandingRead(**asdict(group), share=group.share, to_gain=group.to_gain) for group in prep.groups
        ],
        exam_sets=[ExamSetRead.from_progress(exam) for exam in prep.exam_sets],
        patterns=[
            PrepPatternRead(
                **item.model_dump(exclude={"sources"}),
                sources=_sources(checks),
                scenarios=[
                    PrepScenarioRead(
                        card_id=row.card_id, question_id=row.question_id, topic=row.topic,
                        points=row.points, last_score=row.last_score,
                    )
                    for row in prep.scenarios.get(item.id, [])
                ],
                practice=_practice(prep.scenarios.get(item.id, [])),
            )
            for item, checks in prep.patterns
        ],
        predictions=[
            PrepPredictionRead(**item.model_dump(exclude={"sources"}), sources=_sources(checks))
            for item, checks in prep.predictions
        ],
        tactics=[
            PrepTacticRead(**item.model_dump(exclude={"sources"}), sources=_sources(checks))
            for item, checks in prep.tactics
        ],
        rules=[
            PrepRuleRead(**item.model_dump(exclude={"sources"}), sources=_sources(checks))
            for item, checks in prep.rules
        ],
        plan=[PrepPlanStepRead(**step.model_dump()) for step in prep.plan],
        problems=prep.problems,
    )
