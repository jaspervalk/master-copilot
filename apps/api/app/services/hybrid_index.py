"""In-memory BM25 over de geïndexeerde chunks.

Wordt bij het opstarten en na elke ingest, herindexering of verwijdering
herbouwd vanuit SQL. Op studieschaal (tienduizenden chunks) past dat ruim in
het geheugen en duurt de herbouw milliseconden.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document
from app.services.spoilers import is_hidden

if TYPE_CHECKING:  # pragma: no cover
    from app.schemas import QueryFilters
    from app.services.spoilers import HiddenWeeks
    from app.services.weeks import PageSpan


logger = logging.getLogger(__name__)


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        # Engels
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "of", "in", "on", "for", "to", "from", "with", "by", "as", "at",
        "and", "or", "but", "if", "this", "that", "these", "those",
        "it", "its", "into", "than", "then", "there", "their", "they",
        # Nederlands
        "de", "het", "een", "en", "of", "maar", "als", "dat", "die", "dit",
        "van", "voor", "met", "door", "op", "in", "aan", "bij", "is", "zijn",
        "wordt", "worden", "wat", "hoe", "waarom",
    }
)


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS]


@dataclass(frozen=True)
class SparseEntry:
    """De metadata die nodig is om een BM25-kandidaat te kunnen filteren."""

    chunk_id: str
    course_slug: str
    doc_kind: str
    week: int | None
    assignment_status: str | None
    # Nodig voor het weekleesplan: een boekhoofdstuk hoort bij een week via
    # zijn bladzijden, want het document zelf heeft geen week.
    document_id: str = ""
    page_start: int = 0
    page_end: int = 0


class HybridIndex:
    """BM25 over chunk.normalized_text, met de metadata ernaast."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: list[SparseEntry] = []
        self._bm25: BM25Okapi | None = None
        self._size = 0

    @property
    def size(self) -> int:
        return self._size

    @property
    def ready(self) -> bool:
        return self._bm25 is not None

    def rebuild_from_sql(self, db: Session) -> int:
        """Herbouw over de chunks van documenten met status 'indexed'."""
        stmt = (
            select(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.ingestion_status == "indexed")
        )
        rows = list(db.execute(stmt))

        with self._lock:
            tokenized: list[list[str]] = []
            entries: list[SparseEntry] = []
            for chunk, document in rows:
                tokens = tokenize(chunk.normalized_text)
                if not tokens:
                    continue
                tokenized.append(tokens)
                entries.append(
                    SparseEntry(
                        chunk_id=chunk.id,
                        course_slug=document.course_slug,
                        doc_kind=document.doc_kind,
                        week=document.week,
                        assignment_status=document.assignment_status,
                        document_id=document.id,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                    )
                )

            if not tokenized:
                self._entries = []
                self._bm25 = None
                self._size = 0
                return 0

            self._entries = entries
            self._bm25 = BM25Okapi(tokenized)
            self._size = len(entries)
        return self._size

    @staticmethod
    def _in_week(entry: SparseEntry, week: int, week_spans: "list[PageSpan] | None") -> bool:
        if entry.week == week:
            return True
        # Overlap met een leesstuk telt ook: zo hoort hoofdstuk 9 van het boek
        # bij week 2 zonder dat het boek zelf een week heeft.
        return any(
            span.document_id == entry.document_id
            and entry.page_end >= span.page_start
            and entry.page_start <= span.page_end
            for span in (week_spans or ())
        )

    @staticmethod
    def _matches(
        entry: SparseEntry,
        filters: "QueryFilters | None",
        hidden: "HiddenWeeks | None" = None,
        week_spans: "list[PageSpan] | None" = None,
    ) -> bool:
        # De spoilerfilter gaat vóór alle andere filters: een uitwerking uit een
        # open week komt nooit terug, wat er ook aan filters staat.
        if is_hidden(entry.course_slug, entry.doc_kind, entry.week, hidden):
            return False
        if filters is None:
            return True
        if filters.course_slug and entry.course_slug != filters.course_slug:
            return False
        if filters.week is not None and not HybridIndex._in_week(entry, filters.week, week_spans):
            return False
        if filters.doc_kinds and entry.doc_kind not in filters.doc_kinds:
            return False
        if filters.assignment_status and entry.assignment_status != filters.assignment_status:
            return False
        return True

    def search(
        self,
        query: str,
        limit: int,
        filters: "QueryFilters | None" = None,
        hidden: "HiddenWeeks | None" = None,
        week_spans: "list[PageSpan] | None" = None,
    ) -> list[tuple[str, float]]:
        """BM25 met metadatafilter vóór het rangschikken.

        De sparse tak moet dezelfde filters kennen als de dense tak. Anders zou
        elke gefilterde vraag — en dat is hier vrijwel elke vraag, want er staat
        altijd een vak aan — stilletjes terugvallen op dense-only.
        """
        with self._lock:
            if self._bm25 is None or not self._entries:
                return []
            tokens = tokenize(query)
            if not tokens:
                return []
            scores = self._bm25.get_scores(tokens)
            candidates = [
                (entry.chunk_id, float(score))
                for entry, score in zip(self._entries, scores, strict=True)
                if self._matches(entry, filters, hidden, week_spans)
            ]
        # BM25 kan in kleine corpora nul of negatieve scores geven; de rangorde
        # klopt nog steeds, dus er wordt niet op absolute score afgekapt.
        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates[:limit]


_index: HybridIndex | None = None
_index_lock = threading.Lock()


def get_hybrid_index() -> HybridIndex:
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = HybridIndex()
    return _index


def refresh_hybrid_index(db: Session) -> int:
    try:
        return get_hybrid_index().rebuild_from_sql(db)
    except Exception:
        logger.exception("Herbouw van de BM25-index mislukte; sparse retrieval is uitgeschakeld.")
        return 0


def reset_hybrid_index() -> None:
    """Testhulp — gooi de singleton weg zodat toestand niet tussen tests lekt."""
    global _index
    with _index_lock:
        _index = None


def rrf_fuse(
    dense: list[tuple[str, float]],
    sparse: list[tuple[str, float]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion.

    Elke ranker draagt 1 / (k + rang) bij. De invoer moet aflopend gesorteerd
    zijn op eigen score; alleen de rangpositie telt.
    """
    fused: dict[str, float] = {}
    for rank, (chunk_id, _) in enumerate(dense, start=1):
        fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank)
    for rank, (chunk_id, _) in enumerate(sparse, start=1):
        fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda item: item[1], reverse=True)
