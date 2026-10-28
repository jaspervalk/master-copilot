from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Course, Document, WeekSummary
from app.schemas import BuildSummaryRequest, ExampleRead, WeekRead, WeekSummaryRead
from app.services.weeks import week_scope
from app.services.weeks_summary import NoWeekMaterial, build_summary, is_stale, week_material


router = APIRouter(prefix="/weeks", tags=["weeks"])


def _to_read(db: Session, summary: WeekSummary) -> WeekSummaryRead:
    return WeekSummaryRead(
        course_slug=summary.course_slug,
        week=summary.week,
        stale=is_stale(db, summary),
        chunks_used=summary.chunks_used,
        chunks_total=summary.chunks_total,
        created_at=summary.created_at,
        **(summary.content or {"thread": ""}),
    )


@router.get("", response_model=list[WeekRead])
def get_weeks(db: Annotated[Session, Depends(get_db)], course_slug: str = Query(...)) -> list[WeekRead]:
    """De weken van dit vak: uit de studiewijzer én uit wat er geïndexeerd is.

    Allebei, want een week met colleges maar zonder regel in `course.yml` hoort
    er net zo goed bij als een week die alleen op papier bestaat — en dat
    laatste hoor je juist te zien."""
    course = db.get(Course, course_slug)
    uit_plan = {int(key) for key in (course.week_plans if course else {}) or {}}
    uit_corpus = {
        week
        for (week,) in db.execute(
            select(distinct(Document.week)).where(
                Document.course_slug == course_slug,
                Document.ingestion_status == "indexed",
                Document.week.is_not(None),
            )
        )
    }
    met_samenvatting = {
        week
        for (week,) in db.execute(
            select(WeekSummary.week).where(WeekSummary.course_slug == course_slug)
        )
    }

    weeks: list[WeekRead] = []
    for week in sorted(uit_plan | uit_corpus):
        scope = week_scope(db, course_slug, week)
        weeks.append(
            WeekRead(
                week=week,
                topics=scope.topics,
                lectures=scope.lectures,
                chunk_count=week_material(db, course_slug, week).total,
                has_summary=week in met_samenvatting,
                unresolved=scope.unresolved,
            )
        )
    return weeks


@router.get("/summary", response_model=WeekSummaryRead)
def get_summary(
    db: Annotated[Session, Depends(get_db)],
    course_slug: str = Query(...),
    week: int = Query(..., ge=1, le=60),
) -> WeekSummaryRead:
    summary = db.get(WeekSummary, (course_slug, week))
    if summary is None:
        raise HTTPException(status_code=404, detail="Deze week is nog niet samengevat")
    return _to_read(db, summary)


@router.post("/summary", response_model=WeekSummaryRead)
def make_summary(
    payload: BuildSummaryRequest, db: Annotated[Session, Depends(get_db)]
) -> WeekSummaryRead:
    try:
        summary = build_summary(db, course_slug=payload.course_slug, week=payload.week)
    except NoWeekMaterial as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_read(db, summary)


@router.get("/examples", response_model=list[ExampleRead])
def get_week_examples(
    db: Annotated[Session, Depends(get_db)],
    course_slug: str = Query(...),
    week: int = Query(..., ge=1, le=60),
) -> list[ExampleRead]:
    """De uitgewerkte voorbeelden van deze week, met hun figuur.

    Dezelfde voorbeelden als op de oefenpagina: ze horen bij de stof, niet bij
    één pagina, en op de weekkaart staan ze naast de theorie waar ze bij horen.
    """
    from app.api.routes.study import _example_read
    from app.services.study.examples import examples_for

    return [_example_read(example) for example in examples_for(db, course_slug, week=week)]
