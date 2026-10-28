"""De BM25-index leeft in het geheugen en moet bij het opstarten terugkomen.

Zonder die herbouw is de sparse tak leeg tot de eerste ingest, en valt elke
vraag stil terug op dense-only — precies het gedrag dat de hybride opzet moest
voorkomen.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.models import Chunk, Document
from app.services.hybrid_index import get_hybrid_index, reset_hybrid_index


@pytest.fixture(autouse=True)
def _clean_singleton():
    reset_hybrid_index()
    yield
    reset_hybrid_index()


def _indexed_document(db) -> None:
    document = Document(
        title="Handboek",
        source_path="dl/books/handboek.pdf",
        checksum="0" * 64,
        course_slug="dl",
        doc_kind="book",
        ingestion_status="indexed",
    )
    document.chunks.append(
        Chunk(
            chunk_index=0,
            section_path=None,
            page_start=1,
            page_end=1,
            token_count=3,
            text="Backpropagation chain rule",
            normalized_text="backpropagation chain rule",
            chunk_metadata={},
        )
    )
    db.add(document)
    db.commit()


def test_startup_rebuilds_hybrid_index(db_session, monkeypatch: pytest.MonkeyPatch):
    _indexed_document(db_session)

    from app import main

    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(main, "SessionLocal", sessionmaker(bind=db_session.get_bind(), future=True))

    assert not get_hybrid_index().ready

    with TestClient(main.app):
        index = get_hybrid_index()
        assert index.ready
        assert index.size == 1
