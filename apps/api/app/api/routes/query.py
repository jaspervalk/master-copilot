from __future__ import annotations

from app.api.errors import to_http_exception
from app.schemas import QueryRequest, QueryResponse
from app.services.retrieval import RetrievalService

from fastapi import APIRouter


router = APIRouter()


@router.post("/query", response_model=QueryResponse)
def run_query(payload: QueryRequest) -> QueryResponse:
    """Alleen ophalen — handig om te zien wat de twee takken opleveren."""
    try:
        provider, results = RetrievalService().search(
            payload.question,
            top_k=payload.top_k,
            filters=payload.filters,
            mode=payload.retrieval_mode,
        )
    except Exception as exc:  # noqa: BLE001
        raise to_http_exception(exc) from exc

    return QueryResponse(
        question=payload.question,
        embedding_provider=provider,
        top_k=payload.top_k,
        results=results,
    )
