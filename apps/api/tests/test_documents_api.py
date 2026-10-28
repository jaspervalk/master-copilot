from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import Document
from app.services import documents as documents_service
from app.services.parsing import ParsedDocument, ParsedPage


class _FakeBatch:
    provider = "local-hash"
    model = "local"
    dimensions = 3

    def __init__(self, count: int) -> None:
        self.vectors = [[0.1, 0.2, 0.3] for _ in range(count)]


class _FakeEmbeddings:
    def embed_many(self, texts: list[str]) -> _FakeBatch:
        return _FakeBatch(len(texts))


@pytest.fixture()
def client(db_session, tmp_corpus, fake_qdrant, monkeypatch):
    def fake_parse(path: Path) -> ParsedDocument:
        return ParsedDocument(
            title=path.stem,
            page_count=1,
            pages=[ParsedPage(page_number=1, text="1 Kop\n\n" + " ".join(["woord"] * 60))],
            metadata={},
        )

    monkeypatch.setattr(documents_service, "parse_document", fake_parse)
    monkeypatch.setattr(documents_service, "EmbeddingService", lambda: _FakeEmbeddings())
    monkeypatch.setattr(documents_service, "refresh_hybrid_index", lambda db: 0)

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _upload(client, *, filename="bishop.pdf", course="dl", kind="book", week=None, content=b"%PDF-1.4 x"):
    data = {"course_slug": course, "doc_kind": kind}
    if week is not None:
        data["week"] = str(week)
    return client.post(
        "/api/documents/upload",
        files={"file": (filename, content, "application/pdf")},
        data=data,
    )


def test_upload_writes_into_the_corpus_structure(client, tmp_corpus, db_session):
    response = _upload(client, kind="slides", week=3, filename="cnn slides.pdf")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document"]["source_path"] == "dl/slides/week-03/cnn-slides.pdf"
    assert (tmp_corpus / "dl" / "slides" / "week-03" / "cnn-slides.pdf").exists()
    assert body["document"]["ingestion_status"] == "indexed"
    assert body["chunk_count"] > 0


def test_upload_rejects_a_non_pdf_body(client):
    response = _upload(client, content=b"<html>nee</html>")

    assert response.status_code == 400


def test_upload_rejects_an_unknown_doc_kind(client):
    response = _upload(client, kind="verzonnen")

    assert response.status_code in (400, 422)


def test_duplicate_upload_conflicts_without_overwrite(client):
    _upload(client)

    response = _upload(client)

    assert response.status_code == 409


def test_overwrite_replaces_the_file(client, db_session):
    _upload(client)

    response = client.post(
        "/api/documents/upload",
        files={"file": ("bishop.pdf", b"%PDF-1.4 nieuwe inhoud", "application/pdf")},
        data={"course_slug": "dl", "doc_kind": "book", "overwrite": "true"},
    )

    assert response.status_code == 201, response.text
    assert db_session.query(Document).count() == 1


def test_listing_filters_by_course(client):
    _upload(client, course="dl")
    _upload(client, course="stats", filename="esl.pdf")

    response = client.get("/api/documents", params={"course_slug": "stats"})

    assert response.status_code == 200
    assert [item["course_slug"] for item in response.json()] == ["stats"]


def test_delete_moves_the_file_to_trash(client, tmp_corpus, db_session):
    document_id = _upload(client).json()["document"]["id"]

    response = client.delete(f"/api/documents/{document_id}")

    assert response.status_code == 200
    assert not (tmp_corpus / "dl" / "books" / "bishop.pdf").exists()
    assert (tmp_corpus / ".trash" / "dl" / "books" / "bishop.pdf").exists()
    assert db_session.query(Document).count() == 0


def test_courses_endpoint_summarises_the_corpus(client):
    _upload(client, course="dl", kind="assignment", week=1, filename="opgaven.pdf")
    _upload(client, course="dl", kind="slides", week=1, filename="college.pdf")

    response = client.get("/api/courses")

    assert response.status_code == 200
    course = next(item for item in response.json() if item["slug"] == "dl")
    assert course["document_count"] == 2
    assert course["weeks"] == [1]
    assert course["open_assignment_count"] == 1
