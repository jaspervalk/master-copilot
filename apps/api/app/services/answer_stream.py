"""Antwoorden woord voor woord doorgeven.

De Responses API met `text_format=AnswerDraft` streamt het hele JSON-object
teken voor teken terug. Om alleen de zichtbare antwoordtekst door te geven —
en niet het omliggende JSON — lopen de deltas door een kleine statemachine die
het veld `"answer"` op het hoogste niveau vindt en de inhoud daarvan uitpakt.

Aan het eind wordt het volledige object alsnog geparseerd: dat levert de
citaties en het vertrouwen. De deltas zijn een extra signaal, geen vervanging.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.core.config import settings
from app.schemas import AnswerResponse, QueryChunkResult
from app.services.answering import (
    AnswerDraft,
    AnsweringService,
    build_instructions,
    combine_confidence,
    ensure_inline_citation_markers,
    evidence_confidence,
    normalize_answer_text,
)
from app.services.coach import CoachContext, policy_instruction

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover
    AsyncOpenAI = None


logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    type: str
    data: dict


class AnswerFieldStreamer:
    """Haal de tekens uit het veld `"answer"` van binnenkomende JSON.

    Houdt een buffer aan over deltas heen, zodat een sleutel, escape of
    unicode-reeks die over een chunkgrens valt correct wordt afgehandeld. Zodra
    het sluitende aanhalingsteken is verwerkt is `is_done` waar en geeft
    `feed()` een lege string terug.
    """

    _KEY_TOKEN = '"answer"'

    def __init__(self) -> None:
        self._mode: str = "search_key"
        self._key_buffer: str = ""
        self._unicode_buffer: str = ""

    @property
    def is_done(self) -> bool:
        return self._mode == "done"

    def feed(self, delta: str) -> str:
        out: list[str] = []
        for char in delta:
            if self._mode == "done":
                break
            if self._mode == "search_key":
                self._key_buffer += char
                if self._key_buffer.find(self._KEY_TOKEN) != -1:
                    self._key_buffer = ""
                    self._mode = "after_key"
                else:
                    # Buffer kort houden, maar lang genoeg om de sleutel over
                    # een chunkgrens heen te herkennen.
                    keep = max(0, len(self._key_buffer) - len(self._KEY_TOKEN) + 1)
                    self._key_buffer = self._key_buffer[keep:]
                continue
            if self._mode == "after_key":
                if char == ":":
                    self._mode = "before_value"
                continue
            if self._mode == "before_value":
                if char == '"':
                    self._mode = "in_value"
                continue
            if self._mode == "in_value":
                if char == "\\":
                    self._mode = "escape"
                elif char == '"':
                    self._mode = "done"
                else:
                    out.append(char)
                continue
            if self._mode == "escape":
                if char == "u":
                    self._unicode_buffer = ""
                    self._mode = "unicode"
                elif char == "n":
                    out.append("\n")
                    self._mode = "in_value"
                elif char == "t":
                    out.append("\t")
                    self._mode = "in_value"
                elif char == "r":
                    out.append("\r")
                    self._mode = "in_value"
                elif char == "b":
                    out.append("\b")
                    self._mode = "in_value"
                elif char == "f":
                    out.append("\f")
                    self._mode = "in_value"
                else:
                    out.append(char)
                    self._mode = "in_value"
                continue
            if self._mode == "unicode":
                self._unicode_buffer += char
                if len(self._unicode_buffer) == 4:
                    try:
                        out.append(chr(int(self._unicode_buffer, 16)))
                    except ValueError:
                        pass
                    self._unicode_buffer = ""
                    self._mode = "in_value"
                continue
        return "".join(out)


# Ook een controleteken kan het begin van een gesloopt commando zijn, dus dat
# wordt net zo goed vastgehouden tot het woord af is.
_TRAILING_ESCAPE_RE = re.compile(r"[\\\x08\x0c\x7f\r\t\n][A-Za-z]*$")


class DeltaTextRepairer:
    """Past de reparatie van `normalize_answer_text` toe op losse deltas.

    Of een backslash-n een regelovergang was of het begin van `\\nabla` blijkt
    pas uit wat erachter staat, en dat kan in de volgende delta zitten. Daarom
    wordt een afgebroken commando aan het eind van een stuk vastgehouden tot het
    volgende binnenkomt; `flush()` geeft de rest aan het eind vrij.
    """

    def __init__(self) -> None:
        self._carry = ""

    def feed(self, text: str) -> str:
        buffer = self._carry + text
        self._carry = ""
        match = _TRAILING_ESCAPE_RE.search(buffer)
        if match:
            self._carry, buffer = match.group(0), buffer[: match.start()]
        return normalize_answer_text(buffer)

    def flush(self) -> str:
        rest, self._carry = self._carry, ""
        return normalize_answer_text(rest)


def _async_client():
    if not settings.openai_api_key or AsyncOpenAI is None:
        return None
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def _one_shot(
    service: AnsweringService,
    *,
    question: str,
    retrieval_query: str | None,
    chunks: list[QueryChunkResult],
    provider: str,
    style: str,
    coach: CoachContext | None = None,
    language: str = "auto",
) -> AsyncIterator[StreamEvent]:
    """Val terug op het niet-streamende pad, maar met dezelfde eventvorm.

    De synchrone aanroep gaat naar een thread, zodat één trage vraag niet alle
    andere verzoeken op de event loop blokkeert.
    """
    response = await asyncio.to_thread(
        service.compose_from_chunks,
        question=question,
        retrieval_query=retrieval_query,
        chunks=chunks,
        provider=provider,
        style=style,
        coach=coach,
        language=language,
    )
    if response.answer:
        yield StreamEvent("answer_delta", {"text": response.answer})
    yield StreamEvent("complete", response.model_dump(mode="json"))


async def stream_compose(
    *,
    question: str,
    retrieval_query: str | None,
    chunks: list[QueryChunkResult],
    provider: str,
    style: str = "explain",
    coach: CoachContext | None = None,
    language: str = "auto",
) -> AsyncIterator[StreamEvent]:
    """Geef nul of meer `answer_delta`-events en precies één afsluitend event.

    Het afsluitende event is `complete` (met de volledige AnswerResponse) of
    `error`. Ook het abstentie- en het extractieve pad eindigen zo, zodat de
    frontend maar één manier van renderen hoeft te kennen.
    """
    service = AnsweringService()

    async_client = _async_client()
    if not chunks or async_client is None:
        async for event in _one_shot(
            service,
            question=question,
            retrieval_query=retrieval_query,
            chunks=chunks,
            provider=provider,
            style=style,
            coach=coach,
            language=language,
        ):
            yield event
        return

    extractor = AnswerFieldStreamer()
    repairer = DeltaTextRepairer()
    instructions = build_instructions(
        style, policy_instruction(coach.policy, coach.doc_kind) if coach else None, language
    )

    try:
        async with async_client.responses.stream(
            model=settings.openai_answer_model,
            instructions=instructions,
            input=service._build_prompt(
                question=question, chunks=chunks, pinned=coach.pinned if coach else ()
            ),
            text_format=AnswerDraft,
            store=False,
        ) as stream:
            async for event in stream:
                if event.type == "response.output_text.delta" and not extractor.is_done:
                    text = repairer.feed(extractor.feed(event.delta))
                    if text:
                        yield StreamEvent("answer_delta", {"text": text})
            tail = repairer.flush()
            if tail:
                yield StreamEvent("answer_delta", {"text": tail})
            final_response = await stream.get_final_response()
    except Exception as exc:
        logger.warning("Streamen mislukte, val terug op het gewone pad: %s", exc)
        async for event in _one_shot(
            service,
            question=question,
            retrieval_query=retrieval_query,
            chunks=chunks,
            provider=provider,
            style=style,
            coach=coach,
            language=language,
        ):
            yield event
        return

    parsed: AnswerDraft | None = final_response.output_parsed
    if parsed is None:
        yield StreamEvent("error", {"message": "Het antwoordmodel leverde geen bruikbaar resultaat."})
        return

    retrieved = {chunk.chunk_id: chunk for chunk in chunks}
    answer, citations = service.aligned_citations(
        answer=normalize_answer_text(parsed.answer).strip(),
        chunks=chunks,
        draft_citations=[(item.chunk_id, item.support) for item in parsed.citations],
    )
    if not citations and not parsed.abstained:
        citations = service._citation_records(
            draft_citations=[(chunk.chunk_id, service._quote_preview(chunk.text)) for chunk in chunks[:2]],
            retrieved=retrieved,
        )

    evidence_bucket, evidence_reasons = evidence_confidence(
        chunks, provider=provider, min_score=settings.min_evidence_score
    )
    response = AnswerResponse(
        question=question,
        rewritten_query=retrieval_query,
        answer=ensure_inline_citation_markers(answer, len(citations)),
        abstained=parsed.abstained,
        confidence=combine_confidence(parsed.confidence, evidence_bucket),
        confidence_reasons=[*parsed.confidence_reasons, *evidence_reasons],
        citations=citations,
        retrieved_chunks=chunks,
        embedding_provider=provider,
        answer_model=settings.openai_answer_model,
        answer_style=style,
        answer_language=language,
        coach=coach.echo if coach else None,
    )
    yield StreamEvent("complete", response.model_dump(mode="json"))


__all__ = ["AnswerFieldStreamer", "DeltaTextRepairer", "StreamEvent", "stream_compose"]
