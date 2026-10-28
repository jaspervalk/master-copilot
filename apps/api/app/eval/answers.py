"""Opt-in: het antwoordmodel meedraaien. Kost per case een LLM-aanroep."""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerOutcome:
    text: str
    abstained: bool
    confidence: str
    latency_ms: int | None


# (vraag, vak, top_k, coach) → uitkomst. `coach` is {"document_id", "reveal"}
# of None; het vierde argument bestaat zodat een coach-case dezelfde route
# neemt als de UI.
AnswerFn = Callable[[str, str | None, int, dict | None], AnswerOutcome]


def mentions_ok(text: str, must_mention: list[str]) -> bool | None:
    """Letterlijke substrings, hoofdletterongevoelig. Geen lijst = niet van toepassing."""
    if not must_mention:
        return None
    lowered = text.lower()
    return all(term.lower() in lowered for term in must_mention)


def leaked_terms(text: str, must_not_mention: list[str]) -> list[str]:
    """Verboden termen die tóch in het antwoord staan — het eindantwoord van een opdracht."""
    lowered = text.lower()
    return [term for term in must_not_mention if term.lower() in lowered]


def in_process_answer(mode: str) -> AnswerFn:
    from app.db import SessionLocal
    from app.schemas import CoachOptions, QueryFilters
    from app.services.answering import AnsweringService
    from app.services.coach import load_coach_context

    service = AnsweringService()

    def answer(question: str, course_slug: str | None, top_k: int, coach: dict | None) -> AnswerOutcome:
        filters = QueryFilters(course_slug=course_slug) if course_slug else None
        context = None
        if coach:
            db = SessionLocal()
            try:
                context = load_coach_context(db, CoachOptions(**coach), course_slug)
            finally:
                db.close()
        # Kort: de eval meet of het klopt, niet hoe mooi het is uitgelegd.
        response = service.compose(
            question=question,
            retrieval_query=None,
            top_k=top_k,
            filters=filters,
            mode=mode,
            style="short",
            coach=context,
        )
        return AnswerOutcome(
            text=response.answer,
            abstained=response.abstained,
            confidence=response.confidence,
            latency_ms=response.latency_ms,
        )

    return answer


def api_answer(base_url: str, mode: str, opener: Callable = urllib.request.urlopen) -> AnswerFn:
    base = base_url.rstrip("/")

    def answer(question: str, course_slug: str | None, top_k: int, coach: dict | None) -> AnswerOutcome:
        body = {
            "question": question,
            "top_k": top_k,
            "filters": {"course_slug": course_slug} if course_slug else None,
            "retrieval_mode": mode,
            "answer_style": "short",
            "coach": coach,
        }
        request = urllib.request.Request(
            f"{base}/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener(request, timeout=300) as response:
            payload = json.load(response)
        return AnswerOutcome(
            text=payload["answer"],
            abstained=bool(payload["abstained"]),
            confidence=payload["confidence"],
            latency_ms=payload.get("latency_ms"),
        )

    return answer
