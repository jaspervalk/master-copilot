"""Ingestpijplijn en levenscyclus van documenten.

Volgorde: parse → chunk → embed (alles in het geheugen) → stempel valideren →
SQL schrijven → Qdrant schrijven → SQL committen. Faalt Qdrant, dan rollen we
SQL terug en ruimen we eventuele halve punten op; faalt de commit daarna, dan
halen we de Qdrant-punten alsnog weg. Zo blijven de twee opslagen in de pas.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models import Chunk, Document
from app.services.chunking import ChunkDraft, chunk_document
from app.services.chunking.slides import deck_title
from app.services.embeddings import EmbeddingService
from app.services.hybrid_index import refresh_hybrid_index
from app.services.index_stamp import read_stamp, validate_or_raise, write_stamp
from app.services.parsing import parse_document
from app.services.path_metadata import build_corpus_path
from app.services.qdrant_index import QdrantIndexService
from app.services.storage import file_checksum, move_to_trash, write_bytes
from app.services.upload_safety import validate_upload


logger = logging.getLogger(__name__)


class DuplicateDocumentError(Exception):
    def __init__(self, source_path: str) -> None:
        super().__init__(f"'{source_path}' bestaat al in het corpus")
        self.source_path = source_path


@dataclass
class DeletedDocumentResult:
    document_id: str
    title: str
    deleted_chunk_count: int
    removed_from_index: bool
    trashed_path: str | None


def list_documents(
    db: Session,
    *,
    course_slug: str | None = None,
    doc_kinds: list[str] | None = None,
) -> list[Document]:
    stmt = select(Document).options(selectinload(Document.chunks))
    if course_slug:
        stmt = stmt.where(Document.course_slug == course_slug)
    if doc_kinds:
        stmt = stmt.where(Document.doc_kind.in_(doc_kinds))
    stmt = stmt.order_by(Document.course_slug, Document.doc_kind, Document.week, Document.title)
    return list(db.scalars(stmt).all())


def get_document(db: Session, document_id: str) -> Document | None:
    stmt = select(Document).options(selectinload(Document.chunks)).where(Document.id == document_id)
    return db.scalar(stmt)


def find_document_by_path(db: Session, source_path: str) -> Document | None:
    return db.scalar(select(Document).where(Document.source_path == source_path))


def _chunk_rows(document: Document, drafts: list[ChunkDraft]) -> list[Chunk]:
    return [
        Chunk(
            document_id=document.id,
            chunk_index=draft.chunk_index,
            section_path=draft.section_path,
            page_start=draft.page_start,
            page_end=draft.page_end,
            token_count=draft.token_count,
            text=draft.text,
            normalized_text=draft.normalized_text,
            chunk_metadata=draft.chunk_metadata,
        )
        for draft in drafts
    ]


def index_document(db: Session, document: Document) -> tuple[Document, int, str, int]:
    absolute_path = settings.corpus_dir / document.source_path

    parsed = parse_document(absolute_path)
    if document.doc_kind == "slides":
        # Vóór het chunken: de titel is de wortel van elk sectiepad in het deck.
        parsed.title = deck_title(parsed.title, absolute_path.stem)
    drafts = chunk_document(doc_kind=document.doc_kind, parsed=parsed)
    if not drafts:
        raise ValueError(f"'{document.source_path}' leverde geen chunks op")

    embedding_batch = EmbeddingService().embed_many([draft.text for draft in drafts])

    qdrant = QdrantIndexService()
    validate_or_raise(
        read_stamp(db, qdrant.collection_name),
        provider=embedding_batch.provider,
        model=embedding_batch.model,
        dimensions=embedding_batch.dimensions,
    )

    document.title = parsed.title
    document.page_count = parsed.page_count
    document.extracted_metadata = {"source_metadata": parsed.metadata}

    db.execute(delete(Chunk).where(Chunk.document_id == document.id))
    chunk_rows = _chunk_rows(document, drafts)
    db.add_all(chunk_rows)
    db.flush()

    payload_chunks = [
        {
            "id": chunk.id,
            "document_title": document.title,
            "source_path": document.source_path,
            "course_slug": document.course_slug,
            "doc_kind": document.doc_kind,
            "week": document.week,
            "assignment_status": document.assignment_status,
            "section_path": chunk.section_path,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "text": chunk.text,
            "chunk_metadata": chunk.chunk_metadata,
        }
        for chunk in chunk_rows
    ]

    try:
        qdrant.upsert_chunks(
            document_id=document.id,
            chunks=payload_chunks,
            vectors=embedding_batch.vectors,
        )
    except Exception:
        db.rollback()
        try:
            qdrant.delete_document_chunks(document.id)
        except Exception:
            logger.warning("Opruimen van Qdrant-punten voor %s mislukte", document.id)
        raise

    write_stamp(
        db,
        name=qdrant.collection_name,
        provider=embedding_batch.provider,
        model=embedding_batch.model,
        dimensions=embedding_batch.dimensions,
    )

    document.ingestion_status = "indexed"
    document.parse_error = None
    document.chunk_count = len(chunk_rows)
    document.indexed_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        try:
            qdrant.delete_document_chunks(document.id)
        except Exception:
            logger.warning("Terugdraaien van Qdrant na mislukte commit voor %s mislukte", document.id)
        raise
    db.refresh(document)

    refresh_hybrid_index(db)
    return document, len(chunk_rows), embedding_batch.provider, embedding_batch.dimensions


def ingest_bytes(
    db: Session,
    *,
    content: bytes,
    filename: str,
    course_slug: str,
    doc_kind: str,
    week: int | None,
    overwrite: bool = False,
) -> tuple[Document, int, str, int]:
    """Eén ingestpad voor een upload en voor materiaal uit Canvas: het pad komt
    uit dezelfde functie die de mapstructuur afdwingt, zodat het bestand
    precies belandt waar `sync` het ook zou vinden."""
    # corpus_sync importeert dit bestand; vandaar hier en niet bovenaan.
    from app.services.corpus_sync import recompute_assignment_status, upsert_course_from_yaml

    validate_upload(content, filename)
    destination = build_corpus_path(
        corpus_root=settings.corpus_dir,
        course_slug=course_slug,
        doc_kind=doc_kind,
        week=week,
        filename=filename,
    )
    relative = destination.relative_to(settings.corpus_dir.resolve()).as_posix()
    existing = find_document_by_path(db, relative)
    if (destination.exists() or existing is not None) and not overwrite:
        raise DuplicateDocumentError(relative)

    write_bytes(destination, content)

    document = existing
    if document is None:
        document = Document(
            title=destination.stem.replace("-", " ").replace("_", " ").strip(),
            source_path=relative,
            checksum=file_checksum(content),
            course_slug=course_slug,
            doc_kind=doc_kind,
            week=week,
        )
        db.add(document)
    else:
        document.checksum = file_checksum(content)
        document.course_slug = course_slug
        document.doc_kind = doc_kind
        document.week = week
    db.commit()

    try:
        document, chunk_count, provider, dimensions = index_document(db, document)
    except Exception as exc:
        mark_document_failed(db, document, str(exc))
        raise

    upsert_course_from_yaml(db, course_slug, settings.corpus_dir)
    recompute_assignment_status(db, course_slug)
    db.refresh(document)
    return document, chunk_count, provider, dimensions


def mark_document_failed(db: Session, document: Document, error: str) -> Document:
    db.rollback()
    document.ingestion_status = "failed"
    document.parse_error = error[:2000]
    db.commit()
    db.refresh(document)
    return document


def delete_document(db: Session, document: Document, *, trash: bool = True) -> DeletedDocumentResult:
    document_id = document.id
    title = document.title
    deleted_chunk_count = len(document.chunks)
    removed_from_index = document.ingestion_status == "indexed" or deleted_chunk_count > 0
    absolute_path = settings.corpus_dir / document.source_path

    try:
        QdrantIndexService().delete_document_chunks(document_id)
    except Exception as exc:
        # Eerst de vectoren, dan de rij: mislukt dit, dan laten we de rij staan
        # zodat er geen wezen in de index achterblijven.
        raise RuntimeError(f"Vectoren van '{title}' konden niet worden verwijderd: {exc}") from exc

    db.delete(document)
    db.commit()

    trashed: Path | None = None
    if trash:
        trashed = move_to_trash(
            absolute_path,
            corpus_root=settings.corpus_dir,
            trash_root=settings.trash_dir,
        )

    refresh_hybrid_index(db)
    return DeletedDocumentResult(
        document_id=document_id,
        title=title,
        deleted_chunk_count=deleted_chunk_count,
        removed_from_index=removed_from_index,
        trashed_path=str(trashed) if trashed else None,
    )
