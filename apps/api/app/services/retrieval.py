from __future__ import annotations

from collections.abc import Callable

from app.db import SessionLocal
from app.schemas import QueryChunkResult, QueryFilters, RetrievalMode
from app.services.embeddings import EmbeddingService
from app.services.hybrid_index import get_hybrid_index, rrf_fuse
from app.services.qdrant_index import QdrantIndexService, SearchHit
from app.services.spoilers import HiddenWeeks, open_assignment_weeks
from app.services.weeks import PageSpan, week_scope


# Ruim ophalen per ranker, zodat RRF iets te fuseren heeft.
_FUSION_FETCH = 30


def _hidden_weeks_from_db() -> HiddenWeeks:
    db = SessionLocal()
    try:
        return open_assignment_weeks(db)
    finally:
        db.close()


def _week_spans_from_db(course_slug: str, week: int) -> list[PageSpan]:
    db = SessionLocal()
    try:
        return week_scope(db, course_slug, week).spans
    finally:
        db.close()


class RetrievalService:
    def __init__(
        self,
        hidden_weeks_provider: Callable[[], HiddenWeeks] | None = None,
        week_spans_provider: Callable[[str, int], list[PageSpan]] | None = None,
    ) -> None:
        self.embedding_service = EmbeddingService()
        self.index_service = QdrantIndexService()
        self._sparse = get_hybrid_index()
        # Per aanroep opnieuw bepaald: een deadline die vannacht verstreek moet
        # vanochtend al meetellen zonder herstart. Faalt de database, dan faalt
        # de vraag — nooit stil zonder filter doorgaan.
        self._hidden_weeks = hidden_weeks_provider or _hidden_weeks_from_db
        # Het leesplan van een week: welke hoofdstukken erbij horen. Ook per
        # vraag opgehaald, want course.yml kan tussendoor zijn bijgewerkt.
        self._week_spans = week_spans_provider or _week_spans_from_db

    def search(
        self,
        question: str,
        top_k: int,
        filters: QueryFilters | None = None,
        mode: RetrievalMode = "hybrid",
    ) -> tuple[str, list[QueryChunkResult]]:
        batch = self.embedding_service.embed_query(question)
        query_vector = batch.vectors[0]
        hidden = self._hidden_weeks()
        # Alleen zinvol met een vak erbij: een leesplan hoort bij één vak.
        spans = (
            self._week_spans(filters.course_slug, filters.week)
            if filters and filters.course_slug and filters.week is not None
            else []
        )

        if mode == "dense":
            hits = self.index_service.search(
                vector=query_vector, limit=top_k, filters=filters, hidden=hidden, week_spans=spans
            )
            return batch.provider, [self._to_result(hit) for hit in hits]

        return batch.provider, self._hybrid(
            question=question,
            query_vector=query_vector,
            top_k=top_k,
            filters=filters,
            hidden=hidden,
            week_spans=spans,
        )

    def _hybrid(
        self,
        *,
        question: str,
        query_vector: list[float],
        top_k: int,
        filters: QueryFilters | None,
        hidden: HiddenWeeks | None,
        week_spans: list[PageSpan] | None = None,
    ) -> list[QueryChunkResult]:
        dense_hits = self.index_service.search(
            vector=query_vector, limit=_FUSION_FETCH, filters=filters, hidden=hidden, week_spans=week_spans
        )
        # Beide takken krijgen dezelfde filters én dezelfde spoileruitsluiting;
        # de sparse index kent de metadata zelf, dus een actief vakfilter
        # schakelt de BM25-tak niet uit.
        sparse_hits = (
            self._sparse.search(
                question, limit=_FUSION_FETCH, filters=filters, hidden=hidden, week_spans=week_spans
            )
            if self._sparse.ready
            else []
        )

        if not sparse_hits:
            return [self._to_result(hit) for hit in dense_hits[:top_k]]

        fused = rrf_fuse([(hit.chunk_id, hit.score) for hit in dense_hits], sparse_hits)[:top_k]
        by_id: dict[str, SearchHit] = {hit.chunk_id: hit for hit in dense_hits}

        missing = [chunk_id for chunk_id, _ in fused if chunk_id not in by_id]
        for hit in self.index_service.retrieve_payloads(missing):
            by_id[hit.chunk_id] = hit

        results: list[QueryChunkResult] = []
        for chunk_id, _score in fused:
            hit = by_id.get(chunk_id)
            if hit is not None:
                results.append(self._to_result(hit))
        return results

    @staticmethod
    def _to_result(hit: SearchHit) -> QueryChunkResult:
        payload = hit.payload
        return QueryChunkResult(
            chunk_id=hit.chunk_id,
            document_id=payload.get("document_id", ""),
            document_title=payload.get("document_title", "Zonder titel"),
            source_path=payload.get("source_path", ""),
            course_slug=payload.get("course_slug", ""),
            doc_kind=payload.get("doc_kind", ""),
            week=payload.get("week"),
            assignment_status=payload.get("assignment_status"),
            section_path=payload.get("section_path"),
            page_start=payload.get("page_start", 0),
            page_end=payload.get("page_end", 0),
            score=hit.score,
            text=payload.get("text", ""),
            chunk_metadata=payload.get("chunk_metadata", {}),
        )
