"""Studeren: wat doe je nu, en waar zitten de gaten.

Eén samengesteld antwoord, zoals de agenda: de ronde voor nu, het overzicht per
week en de tentamendatum in één keer. De pagina hoeft dan niet drie keer te
vragen en kan niet halverwege uit de pas lopen.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PracticeCard, utcnow
from app.schemas import (
    ExampleRead,
    ExampleStepRead,
    FillWeekRequest,
    FillWeekResponse,
    MakeExamplesRequest,
    MakeExamplesResponse,
    PaceRead,
    LibraryRead,
    MethodClaimRead,
    ResourceRead,
    TopicResourcesRead,
    PracticeCardRead,
    RejectedCard,
    SessionCardRead,
    StudyExamRead,
    StudyRead,
    StudySessionRead,
    StudyWeekRead,
)
from app.services.practice.generation import NoSourceMaterial, UnknownKind
from app.services.study.coverage import week_coverage
from app.services.study.examples import examples_for, make_examples
from app.services.study.generation import fill_week
from app.services.study.library import load_library, topics_with_resources
from app.services.study.mastery import BEHEERST, NIEUW, ZWAK, card_states
from app.services.study.pace import pace as compute_pace
from app.services.study.session import build_session

router = APIRouter(prefix="/study", tags=["study"])


def _example_read(example) -> ExampleRead:
    return ExampleRead(
        id=example.id,
        week=example.week,
        topic=example.topic,
        title=example.title,
        situation=example.situation,
        steps=[ExampleStepRead(label=step.get("label", ""), body=step.get("body", "")) for step in example.steps or []],
        takeaway=example.takeaway,
        prompt=example.prompt,
        figure_svg=example.figure_svg or "",
        figure_caption=example.figure_caption or "",
        page_start=example.page_start,
        page_end=example.page_end,
    )


def _exam_read(exam) -> StudyExamRead | None:
    if exam is None:
        return None
    return StudyExamRead(name=exam.name, date=exam.day, days_left=exam.days_left, source=exam.source)


@router.get("", response_model=StudyRead)
def get_study(
    db: Annotated[Session, Depends(get_db)],
    course_slug: str = Query(...),
    minutes: int = Query(default=25, ge=5, le=180),
    week: int | None = Query(default=None, ge=1, le=60),
) -> StudyRead:
    now = utcnow()
    session = build_session(db, course_slug, minutes=minutes, now=now, week=week)

    # De ronde noemt alleen kaart-ids; de pagina heeft de hele kaart nodig.
    ids = [item.card_id for item in session.cards]
    cards = {
        card.id: card
        for card in (db.scalars(select(PracticeCard).where(PracticeCard.id.in_(ids))) if ids else [])
    }

    horizon = session.exam.days_left if session.exam else None
    states = card_states(db, course_slug, now=now, horizon_days=horizon)
    weeks = week_coverage(db, course_slug, now=now, states=states)

    per_week: dict[int, list] = {}
    for example in examples_for(db, course_slug):
        per_week.setdefault(example.week or 0, []).append(example)

    totals = {
        "cards": len(states),
        "due": sum(1 for state in states if state.due_at <= now),
        "mastered": sum(1 for state in states if state.state == BEHEERST),
        "weak": sum(1 for state in states if state.state == ZWAK),
        "new": sum(1 for state in states if state.state == NIEUW),
    }

    tempo = compute_pace(db, course_slug, minutes=minutes, now=now)

    return StudyRead(
        course_slug=course_slug,
        now=now,
        exam=_exam_read(session.exam),
        pace=(
            PaceRead(
                exam_name=tempo.exam_name,
                days_left=tempo.days_left,
                cards=tempo.cards,
                reviews_needed=tempo.reviews_needed,
                reviews_possible=tempo.reviews_possible,
                minutes=tempo.minutes,
                minutes_per_day_needed=tempo.minutes_per_day_needed,
                feasible=tempo.feasible,
            )
            if tempo is not None
            else None
        ),
        session=StudySessionRead(
            minutes=session.minutes,
            estimated_minutes=session.estimated_minutes,
            cards=[
                SessionCardRead(
                    card=PracticeCardRead.model_validate(cards[item.card_id]),
                    reason=item.reason,
                    topic=item.topic,
                    procedure=item.procedure,
                    minutes=item.minutes,
                )
                for item in session.cards
                if item.card_id in cards
            ],
            counts=session.counts,
            notes=session.notes,
        ),
        weeks=[
            StudyWeekRead(
                week=week.week,
                lectures=week.lectures,
                topics=week.topics,
                material_chunks=week.material_chunks,
                cards=week.cards,
                new=week.new,
                learning=week.learning,
                mastered=week.mastered,
                weak=week.weak,
                due=week.due,
                topics_without_cards=week.topics_without_cards,
                has_summary=week.has_summary,
                summary_stale=week.summary_stale,
                last_practised=week.last_practised,
                examples=[_example_read(example) for example in per_week.get(week.week, [])],
            )
            for week in weeks
        ],
        totals=totals,
    )


@router.post("/weeks/{week}/cards", response_model=FillWeekResponse)
def post_fill_week(
    week: int, payload: FillWeekRequest, db: Annotated[Session, Depends(get_db)]
) -> FillWeekResponse:
    """Vul de ontbrekende onderwerpen van deze week aan met nieuwe kaarten."""
    try:
        report = fill_week(db, payload.course_slug, week, kind=payload.kind, count=payload.count)
    except UnknownKind as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NoSourceMaterial as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FillWeekResponse(
        week=report.week,
        created=report.created,
        topics_done=report.topics_done,
        skipped=report.skipped,
        rejected=[RejectedCard(label=label, reason=reason) for label, reason in report.rejected],
    )


@router.get("/library", response_model=LibraryRead)
def get_library(
    db: Annotated[Session, Depends(get_db)],
    course_slug: str = Query(...),
) -> LibraryRead:
    """Gratis uitleg bij de onderwerpen van dit vak, plus waarom het programma
    doet wat het doet."""
    library = load_library()
    return LibraryRead(
        course_slug=course_slug,
        topics=[
            TopicResourcesRead(
                week=row.week,
                topic=row.topic,
                resources=[ResourceRead(**vars(resource)) for resource in row.resources],
            )
            for row in topics_with_resources(db, course_slug)
        ],
        method=[MethodClaimRead(**vars(claim)) for claim in library.method],
    )


@router.post("/weeks/{week}/examples", response_model=MakeExamplesResponse)
def post_make_examples(
    week: int, payload: MakeExamplesRequest, db: Annotated[Session, Depends(get_db)]
) -> MakeExamplesResponse:
    """Maak een uitgewerkt voorbeeld bij elk onderwerp van deze week dat er nog
    geen heeft."""
    try:
        report = make_examples(
            db, payload.course_slug, week, count=payload.count, figures=payload.figures
        )
    except NoSourceMaterial as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return MakeExamplesResponse(
        week=report.week,
        created=report.created,
        topics_done=report.topics_done,
        skipped=report.skipped,
        rejected=[RejectedCard(label=label, reason=reason) for label, reason in report.rejected],
        figure_problems=report.figure_problems,
    )
