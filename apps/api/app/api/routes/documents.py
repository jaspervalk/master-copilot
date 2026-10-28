from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.errors import to_http_exception
from app.db import get_db
from app.models import Document
from app.schemas import (
    DeleteDocumentResponse,
    DocumentRead,
    IndexDocumentResponse,
    UploadDocumentResponse,
)
from app.services.corpus_sync import recompute_assignment_status
from app.services.documents import (
    delete_document,
    get_document,
    index_document,
    ingest_bytes,
    list_documents,
    mark_document_failed,
)
from app.services.path_metadata import DOC_KINDS


router = APIRouter()


def _read(document: Document) -> DocumentRead:
    return DocumentRead.model_validate(document)


@router.get("/documents", response_model=list[DocumentRead])
def get_documents(
    db: Annotated[Session, Depends(get_db)],
    course_slug: str | None = Query(default=None),
    doc_kind: list[str] | None = Query(default=None),
) -> list[DocumentRead]:
    documents = list_documents(db, course_slug=course_slug, doc_kinds=doc_kind)
    return [_read(document) for document in documents]


@router.get("/documents/{document_id}", response_model=DocumentRead)
def get_single_document(document_id: str, db: Annotated[Session, Depends(get_db)]) -> DocumentRead:
    document = get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document niet gevonden")
    return _read(document)


@router.post("/documents/upload", response_model=UploadDocumentResponse, status_code=201)
async def upload(
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    course_slug: Annotated[str, Form()],
    doc_kind: Annotated[str, Form()],
    week: Annotated[int | None, Form()] = None,
    overwrite: Annotated[bool, Form()] = False,
) -> UploadDocumentResponse:
    if doc_kind not in DOC_KINDS:
        raise HTTPException(status_code=400, detail=f"Onbekend documentsoort '{doc_kind}'")

    content = await file.read()
    filename = file.filename or "document.pdf"

    # Hetzelfde pad als materiaal uit Canvas: services.documents.ingest_bytes.
    try:
        document, chunk_count, provider, dimensions = ingest_bytes(
            db,
            content=content,
            filename=filename,
            course_slug=course_slug,
            doc_kind=doc_kind,
            week=week,
            overwrite=overwrite,
        )
    except Exception as exc:  # noqa: BLE001 — vertaald naar een HTTP-status
        raise to_http_exception(exc) from exc

    return UploadDocumentResponse(
        document=_read(document),
        chunk_count=chunk_count,
        embedding_provider=provider,
        embedding_dimensions=dimensions,
    )


@router.post("/documents/{document_id}/index", response_model=IndexDocumentResponse)
def reindex(document_id: str, db: Annotated[Session, Depends(get_db)]) -> IndexDocumentResponse:
    document = get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document niet gevonden")
    try:
        document, chunk_count, provider, dimensions = index_document(db, document)
    except Exception as exc:  # noqa: BLE001
        mark_document_failed(db, document, str(exc))
        raise to_http_exception(exc) from exc
    return IndexDocumentResponse(
        document=_read(document),
        chunk_count=chunk_count,
        embedding_provider=provider,
        embedding_dimensions=dimensions,
    )


@router.delete("/documents/{document_id}", response_model=DeleteDocumentResponse)
def remove(document_id: str, db: Annotated[Session, Depends(get_db)]) -> DeleteDocumentResponse:
    document = get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document niet gevonden")
    course_slug = document.course_slug
    try:
        result = delete_document(db, document)
    except Exception as exc:  # noqa: BLE001
        raise to_http_exception(exc) from exc
    recompute_assignment_status(db, course_slug)
    return DeleteDocumentResponse(
        document_id=result.document_id,
        title=result.title,
        deleted_chunk_count=result.deleted_chunk_count,
        removed_from_index=result.removed_from_index,
        trashed_path=result.trashed_path,
    )
