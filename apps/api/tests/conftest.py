from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db import Base


@pytest.fixture(autouse=True)
def _no_canvas(monkeypatch: pytest.MonkeyPatch) -> None:
    """De echte .env heeft een Canvas-token; geen test mag daar per ongeluk
    heen. Wie Canvas wil, zet de instellingen zelf en geeft een stub-opener."""
    monkeypatch.setattr(settings, "canvas_base_url", None)
    monkeypatch.setattr(settings, "canvas_access_token", None)


@pytest.fixture(autouse=True)
def _no_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dezelfde reden als `_no_canvas`: de echte .env heeft een OpenAI-sleutel.
    Een test die vergeet een nepmodel mee te geven zou anders echt bellen — en
    dat merk je pas aan de rekening."""
    monkeypatch.setattr(settings, "openai_api_key", None)


@pytest.fixture(autouse=True)
def _no_ntfy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Met een topic in de echte .env gaat een test die `cli notify` aanroept
    anders echt naar je telefoon."""
    monkeypatch.setattr(settings, "ntfy_topic", None)


@pytest.fixture()
def tmp_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Wijs settings.corpus_dir naar een lege wegwerpmap."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    monkeypatch.setattr(settings, "corpus_dir", corpus)
    yield corpus
    shutil.rmtree(corpus, ignore_errors=True)


@pytest.fixture()
def db_session(tmp_path: Path) -> Iterator:
    """Verse SQLite-database per test."""
    from app import models  # noqa: F401  — registreert de tabellen

    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def fake_qdrant(monkeypatch: pytest.MonkeyPatch):
    """In-memory vervanger voor QdrantIndexService.

    Houdt punten per document bij, zodat tests kunnen controleren dat vectoren
    daadwerkelijk verdwijnen bij verwijderen en dat een mislukte upsert alles
    terugdraait.
    """
    from app.services import documents as documents_service

    class FakeQdrant:
        instances: list["FakeQdrant"] = []

        def __init__(self, *args, **kwargs) -> None:
            self.points: dict[str, list[dict]] = {}
            self.fail_on_upsert = False
            self.collection_name = "test_chunks"
            FakeQdrant.instances.append(self)

        def upsert_chunks(self, document_id: str, chunks: list[dict], vectors: list[list[float]]) -> None:
            if self.fail_on_upsert:
                raise RuntimeError("qdrant down")
            self.points[document_id] = list(chunks)

        def delete_document_chunks(self, document_id: str) -> None:
            self.points.pop(document_id, None)

    FakeQdrant.instances.clear()
    monkeypatch.setattr(documents_service, "QdrantIndexService", FakeQdrant)
    return FakeQdrant
