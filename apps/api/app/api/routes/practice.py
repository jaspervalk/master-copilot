from __future__ import annotations

from typing import Annotated

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.models import PracticeAttempt, PracticeCard
from app.schemas import (
    AttemptRequest,
    AttemptResponse,
    CriterionRead,
    DeckRead,
    DueCountRead,
    ExamSectionRead,
    ExamSetRead,
    GenerateExamSectionRequest,
    GenerateExamSectionResponse,
    GenerateCardsRequest,
    GenerateCardsResponse,
    PracticeCardRead,
    RejectedCard,
)
from app.services.practice.decks import deck_cards, list_decks
from app.services.practice.exams import exam_cards, exam_progress, import_course_exams
from app.services.practice.generation import NoSourceMaterial, UnknownKind, generate_cards
from app.services.practice.practice_exams import NoBlueprint, generate_section
from app.services.practice.grading import (
    LETTERS,
    InvalidChoice,
    NoGrader,
    grade_choice,
    grade_open,
)
from app.services.practice.snippets import outputs_match
from app.services.practice.sandbox import compare, tolerance_for
from app.services.practice.scheduling import due_cards, due_counts


router = APIRouter(prefix="/practice", tags=["practice"])


@router.get("/decks", response_model=list[DeckRead])
def get_decks(
    db: Annotated[Session, Depends(get_db)],
    course_slug: str = Query(...),
    min_chunks: int = Query(default=2, ge=1),
) -> list[DeckRead]:
    """Secties van dit vak. Standaard vanaf twee chunks: van één alinea valt
    weinig te oefenen, en het scheelt honderden losse regels in de lijst."""
    klaar = due_counts(db, course_slug)
    return [
        DeckRead(**deck.__dict__, due_count=klaar.get(deck.section_path, 0))
        for deck in list_decks(db, course_slug, min_chunks=min_chunks)
    ]


@router.get("/due", response_model=list[PracticeCardRead])
def get_due(
    db: Annotated[Session, Depends(get_db)],
    course_slug: str = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
    section_path: str | None = Query(default=None),
) -> list[PracticeCardRead]:
    """De kaarten die aan de beurt zijn, degene die het langst wacht eerst.

    Zonder `section_path` loopt de ronde dwars door de decks heen; dat is juist
    de bedoeling, want herkennen wélke toets je moet doen is de helft van het
    werk en dat oefen je niet als de kaarten per college op een rij staan.
    """
    klaar = due_cards(db, course_slug, section_path=section_path)
    return [PracticeCardRead.model_validate(item.card) for item in klaar[:limit]]


@router.get("/due/count", response_model=DueCountRead)
def get_due_count(db: Annotated[Session, Depends(get_db)], course_slug: str = Query(...)) -> DueCountRead:
    """Voor de teller bij Herhalen. Los van de decks, want tentamenkaarten horen
    bij geen enkel deck en tellen wel mee."""
    return DueCountRead(total=len(due_cards(db, course_slug)))


@router.get("/exams", response_model=list[ExamSetRead])
def get_exams(db: Annotated[Session, Depends(get_db)], course_slug: str = Query(...)) -> list[ExamSetRead]:
    """De (proef)tentamens van dit vak, met per sectie wat je bij je laatste
    poging haalde."""
    return [
        ExamSetRead(
            origin=exam.origin,
            title=exam.title,
            question_count=exam.question_count,
            points=exam.points,
            answered=exam.answered,
            answered_points=exam.answered_points,
            last_score=exam.last_score,
            sections=[ExamSectionRead(**asdict(section)) for section in exam.sections],
        )
        for exam in exam_progress(db, course_slug)
    ]


@router.get("/exams/{origin}/cards", response_model=list[PracticeCardRead])
def get_exam_cards(
    origin: str,
    db: Annotated[Session, Depends(get_db)],
    course_slug: str = Query(...),
    section: int | None = Query(default=None),
) -> list[PracticeCardRead]:
    """In de volgorde van het tentamen, niet door elkaar: zo oefen je ook het
    tempo van een echt tentamen."""
    return [PracticeCardRead.model_validate(card) for card in exam_cards(db, course_slug, origin, section)]


@router.post("/exams/generate", response_model=GenerateExamSectionResponse)
def post_exam_generate(
    payload: GenerateExamSectionRequest, db: Annotated[Session, Depends(get_db)]
) -> GenerateExamSectionResponse:
    """Eén sectie van een oefententamen per aanroep.

    Een heel tentamen is vijf modelaanroepen of meer, samen minuten werk. Per
    sectie kan de pagina tussendoor laten zien hoe ver het is, en valt er bij
    een fout niet alles weg.
    """
    try:
        result = generate_section(
            db, course_slug=payload.course_slug, section_number=payload.section, origin=payload.origin
        )
    except (NoBlueprint, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return GenerateExamSectionResponse(
        origin=result.origin,
        title=result.title,
        section_number=result.section_number,
        section_title=result.section_title,
        created=len(result.created),
        points=result.points,
        planned_points=result.planned_points,
        missing=[slot.label() for slot in result.missing],
        rejected=[RejectedCard(label=label, reason=reason) for label, reason in result.rejected],
        uncovered_topics=result.uncovered_topics,
        source_note=result.source_note,
    )


@router.post("/exams/import")
def post_exam_import(db: Annotated[Session, Depends(get_db)], course_slug: str = Query(...)) -> dict:
    """Lees de transcripties in exams/ opnieuw in, zonder de Qdrant-lock van sync."""
    results = import_course_exams(db, course_slug, settings.corpus_dir)
    return {
        "imports": [result.as_line() for result in results if not result.problems],
        "problems": [result.as_line() for result in results if result.problems],
    }


@router.post("/decks/generate", response_model=GenerateCardsResponse)
def generate(payload: GenerateCardsRequest, db: Annotated[Session, Depends(get_db)]) -> GenerateCardsResponse:
    try:
        report = generate_cards(
            db,
            course_slug=payload.course_slug,
            section_path=payload.section_path,
            count=payload.count,
            kind=payload.kind,
        )
    except (NoSourceMaterial, UnknownKind) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return GenerateCardsResponse(
        created=[PracticeCardRead.model_validate(card) for card in report.created],
        rejected=[RejectedCard(label=label, reason=reason) for label, reason in report.rejected],
    )


@router.get("/cards", response_model=list[PracticeCardRead])
def get_cards(
    db: Annotated[Session, Depends(get_db)],
    course_slug: str = Query(...),
    section_path: str = Query(...),
) -> list[PracticeCardRead]:
    return [PracticeCardRead.model_validate(card) for card in deck_cards(db, course_slug, section_path)]


@router.post("/cards/{card_id}/attempt", response_model=AttemptResponse)
def attempt(
    card_id: str, payload: AttemptRequest, db: Annotated[Session, Depends(get_db)]
) -> AttemptResponse:
    card = db.get(PracticeCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Kaart niet gevonden")

    if card.kind == "mc":
        return _attempt_choice(card, payload.answer, db)
    if card.kind == "open":
        return _attempt_open(card, payload.answer, db)
    if card.kind == "output":
        return _attempt_output(card, payload.answer, db)

    result = compare(card.setup, card.reference_answer, payload.answer, tolerance_for(card.kind))
    # Een kapotte referentie is een kapotte kaart, geen fout antwoord van de
    # student; dat hoort niet als "fout" in zijn pogingen te belanden.
    if result.reference_error:
        raise HTTPException(
            status_code=500,
            detail=f"Deze kaart deugt niet: het referentieantwoord draait niet ({result.reference_error})",
        )

    db.add(
        PracticeAttempt(
            card_id=card.id,
            given_answer=payload.answer,
            correct=result.equal,
            detail=result.candidate_error or f"verwacht {result.expected_repr} / kreeg {result.given_repr}",
        )
    )
    db.commit()

    return AttemptResponse(
        correct=result.equal,
        kind=card.kind,
        reference_answer=card.reference_answer,
        explanation=card.explanation or "",
        expected_repr=result.expected_repr,
        given_repr=result.given_repr,
        error=result.candidate_error,
        section_path=card.section_path,
        page_start=card.page_start,
        page_end=card.page_end,
    )


def _common(card: PracticeCard) -> dict:
    spec = card.spec or {}
    return {
        "kind": card.kind,
        "reference_answer": card.reference_answer,
        "explanation": card.explanation or "",
        "expected_repr": "",
        "given_repr": "",
        "section_path": card.section_path,
        "page_start": card.page_start,
        "page_end": card.page_end,
        "material": spec.get("material") or "",
    }


def _attempt_output(card: PracticeCard, answer: str, db: Session) -> AttemptResponse:
    """Een voorspelde uitvoer tegen wat het fragment echt printte.

    Het antwoord is tekst, geen code: het gaat nooit naar de sandbox. De sleutel
    is bij het maken van de kaart uit het uitvoeren gekomen.
    """
    correct = outputs_match(card.reference_answer, answer)
    db.add(
        PracticeAttempt(
            card_id=card.id,
            given_answer=answer,
            correct=correct,
            detail="" if correct else f"verwacht {card.reference_answer!r} / kreeg {answer.strip()!r}",
        )
    )
    db.commit()
    return AttemptResponse(correct=correct, given_repr=answer.strip(), expected_repr=card.reference_answer, **{
        key: value for key, value in _common(card).items() if key not in ("expected_repr", "given_repr")
    })


def _attempt_choice(card: PracticeCard, answer: str, db: Session) -> AttemptResponse:
    try:
        result = grade_choice(card, answer)
    except InvalidChoice as exc:
        # Een ongeldige keuze is geen fout antwoord; die hoort niet in je pogingen.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def letters(indices: list[int]) -> str:
        return ", ".join(LETTERS[index] for index in indices)

    db.add(
        PracticeAttempt(
            card_id=card.id,
            given_answer=letters(result.selected),
            correct=result.correct,
            detail=f"gekozen {letters(result.selected)} / goed {letters(result.expected)}",
            score=result.score,
            max_score=result.max_score,
        )
    )
    db.commit()
    return AttemptResponse(
        correct=result.correct,
        score=result.score,
        max_score=result.max_score,
        options=(card.spec or {}).get("options") or [],
        selected=result.selected,
        correct_options=result.expected,
        **_common(card),
    )


def _attempt_open(card: PracticeCard, answer: str, db: Session) -> AttemptResponse:
    try:
        result = grade_open(card, answer)
    except NoGrader as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    criteria = [asdict(item) for item in result.criteria]
    db.add(
        PracticeAttempt(
            card_id=card.id,
            given_answer=answer,
            correct=result.correct,
            detail=f"{result.score:g} van {result.max_score:g} punten",
            score=result.score,
            max_score=result.max_score,
            feedback={"criteria": criteria, "feedback": result.feedback},
        )
    )
    db.commit()
    return AttemptResponse(
        correct=result.correct,
        score=result.score,
        max_score=result.max_score,
        criteria=[CriterionRead(**item) for item in criteria],
        feedback=result.feedback,
        **_common(card),
    )


@router.delete("/cards/{card_id}", response_model=PracticeCardRead)
def discard(card_id: str, db: Annotated[Session, Depends(get_db)]) -> PracticeCardRead:
    """Weggooien is uitschakelen, niet wissen: pogingen houden hun verwijzing."""
    card = db.get(PracticeCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Kaart niet gevonden")
    card.disabled = True
    db.commit()
    db.refresh(card)
    return PracticeCardRead.model_validate(card)
