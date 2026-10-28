"""Twee manieren om dezelfde zoekfunctie te leveren.

Embedded Qdrant is single-process: de runner kan niet naast de draaiende API
werken. In-process is de standaard (zoals `sync`); `--api` gaat over HTTP naar
/api/query en gebruikt dus precies dezelfde code en filters.
"""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.eval.metrics import Hit
from app.eval.runner import SearchFn
from app.models import Document


def hits_from_results(results: list[dict]) -> list[Hit]:
    return [
        Hit(
            source_path=item["source_path"],
            page_start=int(item["page_start"]),
            page_end=int(item["page_end"]),
            score=float(item.get("score") or 0.0),
        )
        for item in results
    ]


def in_process_search(mode: str) -> SearchFn:
    # Import hier, zodat het laden van de module geen Qdrant-client opent.
    from app.schemas import QueryFilters
    from app.services.retrieval import RetrievalService

    service = RetrievalService()

    def search(question: str, course_slug: str | None, top_k: int) -> list[Hit]:
        filters = QueryFilters(course_slug=course_slug) if course_slug else None
        _, results = service.search(question, top_k=top_k, filters=filters, mode=mode)
        return hits_from_results([r.model_dump() for r in results])

    return search


def _post_json(opener: Callable, url: str, body: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener(request, timeout=120) as response:
        return json.load(response)


def _get_json(opener: Callable, url: str):
    request = urllib.request.Request(url, method="GET")
    with opener(request, timeout=60) as response:
        return json.load(response)


def api_search(base_url: str, mode: str, opener: Callable = urllib.request.urlopen) -> SearchFn:
    base = base_url.rstrip("/")

    def search(question: str, course_slug: str | None, top_k: int) -> list[Hit]:
        body = {
            "question": question,
            "top_k": top_k,
            "filters": {"course_slug": course_slug} if course_slug else None,
            "retrieval_mode": mode,
        }
        payload = _post_json(opener, f"{base}/api/query", body)
        return hits_from_results(payload["results"])

    return search


def known_paths_in_process(db: Session) -> set[str]:
    return set(db.scalars(select(Document.source_path)))


def known_paths_api(base_url: str, opener: Callable = urllib.request.urlopen) -> set[str]:
    documents = _get_json(opener, f"{base_url.rstrip('/')}/api/documents")
    return {item["source_path"] for item in documents}


# source_path → document_id. Coach-cases noemen een pad (stabiel), de API wil
# een id (verandert bij herindexering); de vertaling gebeurt per run.
def document_ids_in_process(db: Session) -> dict[str, str]:
    return {path: id_ for id_, path in db.execute(select(Document.id, Document.source_path))}


def document_ids_api(base_url: str, opener: Callable = urllib.request.urlopen) -> dict[str, str]:
    documents = _get_json(opener, f"{base_url.rstrip('/')}/api/documents")
    return {item["source_path"]: item["id"] for item in documents}
