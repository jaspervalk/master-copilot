from pathlib import Path

import pytest

from app.models import Chunk, Document
from app.services import documents as documents_service
from app.services.parsing import ParsedDocument, ParsedPage


@pytest.fixture(autouse=True)
def _stub_parsing_and_embeddings(monkeypatch):
    def fake_parse(path: Path) -> ParsedDocument:
        return ParsedDocument(
            title="Bishop PRML",
            page_count=2,
            pages=[
                ParsedPage(page_number=1, text="5 Neural Networks\n\n" + " ".join(["woord"] * 200)),
                ParsedPage(page_number=2, text=" ".join(["woord"] * 200)),
            ],
            metadata={},
        )

    class FakeBatch:
        provider = "local-hash"
        model = "local"
        dimensions = 3

        def __init__(self, count: int) -> None:
            self.vectors = [[0.1, 0.2, 0.3] for _ in range(count)]

    class FakeEmbeddings:
        def embed_many(self, texts: list[str]) -> FakeBatch:
            return FakeBatch(len(texts))

    monkeypatch.setattr(documents_service, "parse_document", fake_parse)
    monkeypatch.setattr(documents_service, "EmbeddingService", lambda: FakeEmbeddings())
    monkeypatch.setattr(documents_service, "refresh_hybrid_index", lambda db: 0)


def _document(tmp_corpus: Path, db_session) -> Document:
    source = tmp_corpus / "dl" / "books" / "bishop.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4 fake")

    document = Document(
        title="bishop",
        source_path="dl/books/bishop.pdf",
        checksum="d" * 64,
        course_slug="dl",
        doc_kind="book",
        week=None,
    )
    db_session.add(document)
    db_session.commit()
    return document


def test_indexing_writes_chunks_and_marks_indexed(tmp_corpus, db_session, fake_qdrant):
    document = _document(tmp_corpus, db_session)

    _document_out, chunk_count, provider, dimensions = documents_service.index_document(db_session, document)

    assert chunk_count > 0
    assert provider == "local-hash"
    assert dimensions == 3
    assert document.ingestion_status == "indexed"
    assert document.title == "Bishop PRML"
    assert document.chunk_count == chunk_count
    assert document.indexed_at is not None
    assert db_session.query(Chunk).count() == chunk_count


def test_qdrant_payload_carries_course_metadata(tmp_corpus, db_session, fake_qdrant):
    document = _document(tmp_corpus, db_session)

    documents_service.index_document(db_session, document)

    payload = fake_qdrant.instances[-1].points[document.id][0]
    assert payload["course_slug"] == "dl"
    assert payload["doc_kind"] == "book"
    assert payload["source_path"] == "dl/books/bishop.pdf"


def test_reindexing_replaces_old_chunks(tmp_corpus, db_session, fake_qdrant):
    document = _document(tmp_corpus, db_session)
    documents_service.index_document(db_session, document)
    first_count = db_session.query(Chunk).count()

    documents_service.index_document(db_session, document)

    assert db_session.query(Chunk).count() == first_count


def test_qdrant_failure_rolls_back_sql(tmp_corpus, db_session, fake_qdrant, monkeypatch):
    document = _document(tmp_corpus, db_session)

    class FailingQdrant(fake_qdrant):
        def upsert_chunks(self, document_id, chunks, vectors):
            raise RuntimeError("qdrant down")

    monkeypatch.setattr(documents_service, "QdrantIndexService", FailingQdrant)

    with pytest.raises(RuntimeError):
        documents_service.index_document(db_session, document)

    db_session.rollback()
    assert db_session.query(Chunk).count() == 0


def test_delete_removes_chunks_and_trashes_the_file(tmp_corpus, db_session, fake_qdrant):
    document = _document(tmp_corpus, db_session)
    documents_service.index_document(db_session, document)

    result = documents_service.delete_document(db_session, document)

    assert result.deleted_chunk_count > 0
    assert db_session.query(Document).count() == 0
    assert db_session.query(Chunk).count() == 0
    assert not (tmp_corpus / "dl" / "books" / "bishop.pdf").exists()
    assert result.trashed_path is not None
    assert Path(result.trashed_path).exists()
