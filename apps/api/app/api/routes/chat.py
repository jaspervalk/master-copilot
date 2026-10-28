from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import to_http_exception
from app.db import get_db
from app.schemas import ChatRequest, ChatResponse
from app.services import conversations, query_logs
from app.services.answering import AnsweringService
from app.services.coach import CoachError, load_coach_context


router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Annotated[Session, Depends(get_db)]) -> ChatResponse:
    started = time.perf_counter()
    course_slug = payload.filters.course_slug if payload.filters else None
    conversation = conversations.get_or_create(db, payload.conversation_id, course_slug=course_slug)

    coach = None
    if payload.coach is not None:
        try:
            coach = load_coach_context(db, payload.coach, course_slug)
        except CoachError as exc:
            raise to_http_exception(exc) from exc

    service = AnsweringService()

    previous_turns = conversations.history(db, conversation.id)
    retrieval_query = conversations.rewrite_followup(
        history=previous_turns,
        question=payload.question,
        client=service.client,
    )

    try:
        response = service.compose(
            question=payload.question,
            retrieval_query=retrieval_query,
            top_k=payload.top_k,
            filters=payload.filters,
            mode=payload.retrieval_mode,
            style=payload.answer_style,
            coach=coach,
            language=payload.answer_language,
        )
    except Exception as exc:  # noqa: BLE001
        query_logs.log_failure(
            endpoint="chat",
            question=payload.question,
            filters=payload.filters,
            top_k=payload.top_k,
            error=str(exc),
            conversation_id=conversation.id,
        )
        raise to_http_exception(exc) from exc

    conversations.record_turn(db, conversation, question=payload.question, answer=response)
    query_logs.log_answer(
        endpoint="chat",
        question=payload.question,
        response=response,
        filters=payload.filters,
        top_k=payload.top_k,
        mode=payload.retrieval_mode,
        conversation_id=conversation.id,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )

    return ChatResponse(conversation_id=conversation.id, **response.model_dump())
