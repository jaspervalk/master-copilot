"""Streamend chat-eindpunt via Server-Sent Events.

Volgorde van de frames:
  1. `retrieval` — zodra het ophalen klaar is; bevat het gespreks-id en de
     gevonden fragmenten, zodat de UI het bronpaneel kan vullen vóór het
     antwoord begint te lopen.
  2. `answer_delta` — nul of meer tekstfragmenten.
  3. `complete` — het volledige antwoord, of `error` bij een fout.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import AnswerResponse, ChatRequest
from app.services import conversations, query_logs
from app.api.errors import to_http_exception
from app.services.answer_stream import stream_compose
from app.services.answering import AnsweringService
from app.services.coach import CoachError, load_coach_context


logger = logging.getLogger(__name__)

router = APIRouter()


def _format_event(event: str, data: object) -> str:
    payload = json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, db: Annotated[Session, Depends(get_db)]) -> StreamingResponse:
    course_slug = payload.filters.course_slug if payload.filters else None
    conversation = conversations.get_or_create(db, payload.conversation_id, course_slug=course_slug)
    conversation_id = conversation.id

    # Vóór de stream begint: een ongeldige coachkeuze hoort een gewone 400 te
    # zijn, geen foutframe halverwege een SSE-verbinding.
    coach = None
    if payload.coach is not None:
        try:
            coach = load_coach_context(db, payload.coach, course_slug)
        except CoachError as exc:
            raise to_http_exception(exc) from exc

    async def generate() -> AsyncIterator[str]:
        started = time.perf_counter()
        final_response: AnswerResponse | None = None

        try:
            service = AnsweringService()

            previous_turns = conversations.history(db, conversation_id)
            retrieval_query = await asyncio.to_thread(
                conversations.rewrite_followup,
                history=previous_turns,
                question=payload.question,
                client=service.client,
            )

            provider, chunks = await asyncio.to_thread(
                service.retrieve,
                retrieval_query or payload.question,
                payload.top_k,
                payload.filters,
                payload.retrieval_mode,
            )

            yield _format_event(
                "retrieval",
                {
                    "type": "retrieval",
                    "conversation_id": conversation_id,
                    "embedding_provider": provider,
                    "rewritten_query": retrieval_query,
                    "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
                },
            )

            async for event in stream_compose(
                question=payload.question,
                retrieval_query=retrieval_query,
                chunks=chunks,
                provider=provider,
                style=payload.answer_style,
                coach=coach,
                language=payload.answer_language,
            ):
                yield _format_event(event.type, {"type": event.type, **event.data})
                if event.type == "complete":
                    final_response = AnswerResponse.model_validate(event.data)
                elif event.type == "error":
                    raise RuntimeError(event.data.get("message") or "stream_compose gaf een fout")

            latency_ms = int((time.perf_counter() - started) * 1000)
            if final_response is not None:
                final_response.latency_ms = latency_ms
                conversations.record_turn(
                    db, conversation, question=payload.question, answer=final_response
                )
                query_logs.log_answer(
                    endpoint="stream",
                    question=payload.question,
                    response=final_response,
                    filters=payload.filters,
                    top_k=payload.top_k,
                    mode=payload.retrieval_mode,
                    conversation_id=conversation_id,
                    latency_ms=latency_ms,
                )

        except Exception as exc:  # noqa: BLE001 — afsluitend SSE-foutframe
            logger.exception("Streamend antwoord mislukte: %s", exc)
            query_logs.log_failure(
                endpoint="stream",
                question=payload.question,
                filters=payload.filters,
                top_k=payload.top_k,
                error=str(exc),
                conversation_id=conversation_id,
            )
            yield _format_event("error", {"type": "error", "message": str(exc)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
