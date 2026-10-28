"""Elke vraag wordt vastgelegd — dit is straks de eval-dataset van fase 4.

De log gebruikt een eigen sessie: een mislukte logregel mag de transactie van
het verzoek zelf nooit vergiftigen.
"""
from __future__ import annotations

import logging

from app.db import SessionLocal
from app.models import QueryLog
from app.schemas import AnswerResponse, QueryFilters


logger = logging.getLogger(__name__)


def _filters_payload(filters: QueryFilters | None) -> dict:
    return filters.model_dump(exclude_none=True, mode="json") if filters else {}


def log_answer(
    *,
    endpoint: str,
    question: str,
    response: AnswerResponse,
    filters: QueryFilters | None,
    top_k: int,
    mode: str,
    conversation_id: str | None,
    latency_ms: int | None,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            QueryLog(
                conversation_id=conversation_id,
                endpoint=endpoint,
                question=question,
                rewritten_query=response.rewritten_query,
                filters=_filters_payload(filters),
                retrieval_mode=mode,
                answer_style=response.answer_style,
                top_k=top_k,
                retrieved_chunk_ids=[chunk.chunk_id for chunk in response.retrieved_chunks],
                retrieved_documents=[chunk.document_id for chunk in response.retrieved_chunks],
                retrieved_scores=[chunk.score for chunk in response.retrieved_chunks],
                embedding_provider=response.embedding_provider,
                answer_model=response.answer_model,
                abstained=response.abstained,
                confidence=response.confidence,
                confidence_inputs={"reasons": response.confidence_reasons},
                citations=[citation.model_dump(mode="json") for citation in response.citations],
                latency_ms=latency_ms,
                status="ok",
            )
        )
        db.commit()
    except Exception:
        logger.exception("Vastleggen van de vraag mislukte.")
        db.rollback()
    finally:
        db.close()


def log_failure(
    *,
    endpoint: str,
    question: str,
    filters: QueryFilters | None,
    top_k: int,
    error: str,
    conversation_id: str | None,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            QueryLog(
                conversation_id=conversation_id,
                endpoint=endpoint,
                question=question,
                filters=_filters_payload(filters),
                top_k=top_k,
                status="error",
                error=error[:2000],
            )
        )
        db.commit()
    except Exception:
        logger.exception("Vastleggen van de fout mislukte.")
        db.rollback()
    finally:
        db.close()
