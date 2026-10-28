from __future__ import annotations

import logging
import threading
import warnings
from dataclasses import dataclass, field
from itertools import islice
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.services.spoilers import HIDDEN_KINDS

if TYPE_CHECKING:  # pragma: no cover — alleen voor typecontrole
    from app.schemas import QueryFilters
    from app.services.spoilers import HiddenWeeks
    from app.services.weeks import PageSpan

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
except ImportError:  # pragma: no cover
    QdrantClient = None
    models = None


logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    chunk_id: str
    score: float
    payload: dict = field(default_factory=dict)


_client: Any | None = None
_client_lock = threading.Lock()


def _build_client() -> Any:
    if QdrantClient is None:  # pragma: no cover
        raise RuntimeError("qdrant-client is niet geïnstalleerd")
    if settings.qdrant_url:
        return QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=settings.qdrant_timeout_seconds,
        )
    settings.qdrant_local_path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(settings.qdrant_local_path))


def get_qdrant_client() -> Any:
    """Eén client per proces: de embedded modus vergrendelt zijn opslagmap."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _build_client()
    return _client


def close_qdrant_client() -> None:
    global _client
    with _client_lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:  # pragma: no cover
                pass
            _client = None


def build_filter(
    filters: "QueryFilters | None",
    hidden: "HiddenWeeks | None" = None,
    week_spans: "list[PageSpan] | None" = None,
):
    """QueryFilters, spoileruitsluiting en het leesplan van de week → Qdrant-filter."""
    conditions = []
    should = []
    if filters is not None:
        if filters.course_slug:
            conditions.append(
                models.FieldCondition(key="course_slug", match=models.MatchValue(value=filters.course_slug))
            )
        if filters.week is not None:
            week_match = models.FieldCondition(key="week", match=models.MatchValue(value=filters.week))
            if not week_spans:
                conditions.append(week_match)
            else:
                # Met een leesplan telt óók wat in het boek bij die week hoort.
                # Een boek heeft zelf geen week, dus dat kan alleen via de
                # bladzijden waar het hoofdstuk staat.
                should.append(models.Filter(must=[week_match]))
                for span in week_spans:
                    should.append(
                        models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="document_id", match=models.MatchValue(value=span.document_id)
                                ),
                                models.FieldCondition(key="page_end", range=models.Range(gte=span.page_start)),
                                models.FieldCondition(key="page_start", range=models.Range(lte=span.page_end)),
                            ]
                        )
                    )
        if filters.doc_kinds:
            conditions.append(
                models.FieldCondition(key="doc_kind", match=models.MatchAny(any=list(filters.doc_kinds)))
            )
        if filters.assignment_status:
            conditions.append(
                models.FieldCondition(
                    key="assignment_status", match=models.MatchValue(value=filters.assignment_status)
                )
            )

    # Eén must_not per (vak, week): een uitwerking uit die week van dat vak.
    # Zonder vakfilter geldt de uitsluiting nog steeds per vak van de chunk.
    must_not = [
        models.Filter(
            must=[
                models.FieldCondition(key="course_slug", match=models.MatchValue(value=course_slug)),
                models.FieldCondition(key="doc_kind", match=models.MatchAny(any=list(HIDDEN_KINDS))),
                models.FieldCondition(key="week", match=models.MatchValue(value=week)),
            ]
        )
        for course_slug, weeks in (hidden or {}).items()
        for week in sorted(weeks)
    ]

    if not conditions and not must_not and not should:
        return None
    return models.Filter(must=conditions, must_not=must_not or None, should=should or None)


class QdrantIndexService:
    def __init__(self, client: Any | None = None) -> None:
        if models is None:  # pragma: no cover
            raise RuntimeError("qdrant-client is niet geïnstalleerd")
        self.client = client if client is not None else get_qdrant_client()
        self.collection_name = settings.qdrant_collection_name

    @staticmethod
    def _batched(points: list, size: int):
        iterator = iter(points)
        while batch := list(islice(iterator, size)):
            yield batch

    def _ensure_payload_indexes(self) -> None:
        indexed_fields = {
            "document_id": models.PayloadSchemaType.KEYWORD,
            "course_slug": models.PayloadSchemaType.KEYWORD,
            "doc_kind": models.PayloadSchemaType.KEYWORD,
            "assignment_status": models.PayloadSchemaType.KEYWORD,
            "week": models.PayloadSchemaType.INTEGER,
            "page_start": models.PayloadSchemaType.INTEGER,
            "page_end": models.PayloadSchemaType.INTEGER,
        }

        # De embedded Qdrant negeert payload-indexen en waarschuwt daarover per
        # veld. Dat is hier geen nieuws — filteren gebeurt lokaal gewoon lineair —
        # dus de waarschuwing wordt gedempt in plaats van zeven keer per sync
        # over het scherm te lopen.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*[Pp]ayload indexes have no effect.*")
            for field_name, schema in indexed_fields.items():
                try:
                    self.client.create_payload_index(
                        collection_name=self.collection_name,
                        field_name=field_name,
                        field_schema=schema,
                        wait=True,
                    )
                except Exception:
                    continue

    def collection_exists(self) -> bool:
        try:
            self.client.get_collection(self.collection_name)
            return True
        except Exception:
            return False

    def collection_dimensions(self) -> int | None:
        try:
            collection = self.client.get_collection(self.collection_name)
        except Exception:
            return None
        configured = collection.config.params.vectors
        return getattr(configured, "size", None)

    def ensure_collection(self, dimensions: int) -> bool:
        """Zorg dat de collectie bestaat op deze dimensie. True als hij is aangemaakt."""
        existing_size = self.collection_dimensions()
        if existing_size is None:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE),
            )
            self._ensure_payload_indexes()
            return True

        if existing_size != dimensions:
            raise RuntimeError(
                f"Bestaande Qdrant-collectie heeft dimensie {existing_size}, verwacht {dimensions}"
            )

        self._ensure_payload_indexes()
        return False

    def upsert_chunks(self, document_id: str, chunks: list[dict], vectors: list[list[float]]) -> None:
        """Verwijder de bestaande punten van dit document en zet de nieuwe erin.

        De aanroeper heeft de provider-stempel al gevalideerd; hier wordt alleen
        de vectordimensie gecontroleerd.
        """
        if not chunks:
            return

        self.ensure_collection(len(vectors[0]))
        self.delete_document_chunks(document_id)

        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            payload = {
                "chunk_id": chunk["id"],
                "document_id": document_id,
                "document_title": chunk["document_title"],
                "source_path": chunk["source_path"],
                "course_slug": chunk["course_slug"],
                "doc_kind": chunk["doc_kind"],
                "week": chunk["week"],
                "assignment_status": chunk["assignment_status"],
                "section_path": chunk["section_path"],
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "text": chunk["text"],
                "chunk_metadata": chunk["chunk_metadata"],
            }
            points.append(models.PointStruct(id=chunk["id"], vector=vector, payload=payload))

        for batch in self._batched(points, max(1, settings.qdrant_upsert_batch_size)):
            self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
                wait=True,
                timeout=settings.qdrant_timeout_seconds,
            )

    def delete_document_chunks(self, document_id: str) -> None:
        if not self.collection_exists():
            return

        selector = models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id),
                    )
                ]
            )
        )
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=selector,
            wait=True,
            timeout=settings.qdrant_timeout_seconds,
        )

    def search(
        self,
        vector: list[float],
        limit: int,
        filters: "QueryFilters | None" = None,
        hidden: "HiddenWeeks | None" = None,
        week_spans: "list[PageSpan] | None" = None,
    ) -> list[SearchHit]:
        query_filter = build_filter(filters, hidden, week_spans)
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                limit=limit,
                query_filter=query_filter,
                with_payload=True,
            )
            results = response.points
        else:  # pragma: no cover
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=vector,
                limit=limit,
                query_filter=query_filter,
                with_payload=True,
            )
        return [
            SearchHit(
                chunk_id=str(result.id),
                score=float(result.score),
                payload=result.payload or {},
            )
            for result in results
        ]

    def retrieve_payloads(self, chunk_ids: list[str]) -> list[SearchHit]:
        """Haal payloads op voor chunks die alleen de sparse tak vond.

        Hun dense score is onbekend; die wordt eerlijk op 0.0 gezet in plaats van
        een score te verzinnen.
        """
        if not chunk_ids:
            return []
        try:
            points = self.client.retrieve(
                collection_name=self.collection_name,
                ids=chunk_ids,
                with_payload=True,
            )
        except Exception:
            return []
        return [SearchHit(chunk_id=str(point.id), score=0.0, payload=point.payload or {}) for point in points]
