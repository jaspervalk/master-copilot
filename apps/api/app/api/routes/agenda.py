from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.errors import to_http_exception
from app.db import get_db
from app.models import CanvasCourse, CanvasFile, CanvasItem, CanvasPage, Task, utcnow
from app.schemas import (
    AgendaItemPatch,
    AgendaItemRead,
    AgendaRead,
    AssignmentTextRequest,
    AssignmentTextResponse,
    CanvasCoursePatch,
    CanvasCourseRead,
    CanvasSyncResponse,
    DocumentRead,
    MaterialFetchRequest,
    MaterialFetchResponse,
    MaterialIgnoreRequest,
    MaterialRead,
    PageFetchRequest,
    PageFetchResponse,
    PageRead,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)
from app.services.canvas.agenda import build_agenda, item_read_for, material_read_for, page_read_for, task_read, utc
from app.services.canvas.client import CanvasError, CanvasNotConfigured, client_from_settings
from app.services.canvas.materials import fetch_assignment_text, fetch_material, fetch_page, set_ignored, set_page_ignored
from app.services.canvas.sync import sync_canvas


router = APIRouter(prefix="/agenda", tags=["agenda"])


# Losse functies zodat tests ze kunnen vervangen: een stub-client, een vaste klok.
def _client():
    return client_from_settings()


def _now():
    return utcnow()


@router.get("", response_model=AgendaRead)
def get_agenda(db: Annotated[Session, Depends(get_db)]) -> AgendaRead:
    return build_agenda(db, now=_now(), configured=_client() is not None)


@router.post("/sync", response_model=CanvasSyncResponse)
def sync(db: Annotated[Session, Depends(get_db)]) -> CanvasSyncResponse:
    client = _client()
    if client is None:
        raise to_http_exception(CanvasNotConfigured())
    now = _now()
    try:
        report = sync_canvas(db, client, now=now)
    except CanvasError as exc:
        raise to_http_exception(exc) from exc
    return CanvasSyncResponse(
        synced_at=utc(now),
        courses=report.courses,
        items=report.items,
        announcements=report.announcements,
        files_new=report.files_new,
        lines=report.as_lines(),
        problems=[f"course.yml {slug}: {problem}" for slug, problem in report.course_problems],
    )


@router.patch("/courses/{canvas_id}", response_model=CanvasCourseRead)
def patch_course(
    canvas_id: int, payload: CanvasCoursePatch, db: Annotated[Session, Depends(get_db)]
) -> CanvasCourseRead:
    course = db.get(CanvasCourse, canvas_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Onbekend Canvas-vak")
    course.hidden = payload.hidden
    db.commit()
    return CanvasCourseRead(canvas_id=course.id, name=course.name, hidden=course.hidden)


@router.patch("/items/{item_id}", response_model=AgendaItemRead)
def patch_item(item_id: str, payload: AgendaItemPatch, db: Annotated[Session, Depends(get_db)]) -> AgendaItemRead:
    """Het vinkje dat Canvas zelf niet kan zetten (papieren tentamen)."""
    item = db.get(CanvasItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Onbekend item")
    now = _now()
    item.done_at = now if payload.done else None
    # Uitvinken moet ook winnen van het vinkje dat je in Canvas zette; aanvinken
    # geeft Canvas zijn zeggenschap terug.
    item.unmarked_at = None if payload.done else now
    db.commit()
    return item_read_for(db, item, now=now)


@router.post("/materials/{file_id}/fetch", response_model=MaterialFetchResponse)
def fetch(file_id: int, payload: MaterialFetchRequest, db: Annotated[Session, Depends(get_db)]) -> MaterialFetchResponse:
    """Het bestand op de voorgestelde plek zetten, of op de plek die de
    gebruiker kiest — en indexeren, via hetzelfde pad als een upload."""
    if db.get(CanvasFile, file_id) is None:
        raise HTTPException(status_code=404, detail="Onbekend Canvas-bestand")
    client = _client()
    if client is None:
        raise to_http_exception(CanvasNotConfigured())
    try:
        file, document, chunk_count = fetch_material(
            db, client, file_id, doc_kind=payload.doc_kind, week=payload.week, overwrite=payload.overwrite
        )
    except Exception as exc:  # noqa: BLE001 — vertaald naar een HTTP-status
        raise to_http_exception(exc) from exc
    return MaterialFetchResponse(
        material=material_read_for(db, file),
        document=DocumentRead.model_validate(document),
        chunk_count=chunk_count,
    )


@router.post("/materials/{file_id}/ignore", response_model=MaterialRead)
def ignore(file_id: int, payload: MaterialIgnoreRequest, db: Annotated[Session, Depends(get_db)]) -> MaterialRead:
    if db.get(CanvasFile, file_id) is None:
        raise HTTPException(status_code=404, detail="Onbekend Canvas-bestand")
    return material_read_for(db, set_ignored(db, file_id, payload.ignored))


@router.post("/pages/{page_id}/fetch", response_model=PageFetchResponse)
def fetch_canvas_page(page_id: str, payload: PageFetchRequest, db: Annotated[Session, Depends(get_db)]) -> PageFetchResponse:
    """Een modulepagina als markdown in het corpus, via hetzelfde pad als een upload."""
    if db.get(CanvasPage, page_id) is None:
        raise HTTPException(status_code=404, detail="Onbekende pagina")
    client = _client()
    if client is None:
        raise to_http_exception(CanvasNotConfigured())
    try:
        page, document, chunk_count = fetch_page(db, client, page_id, overwrite=payload.overwrite)
    except Exception as exc:  # noqa: BLE001 — vertaald naar een HTTP-status
        raise to_http_exception(exc) from exc
    return PageFetchResponse(page=page_read_for(db, page), document=DocumentRead.model_validate(document), chunk_count=chunk_count)


@router.post("/pages/{page_id}/ignore", response_model=PageRead)
def ignore_page(page_id: str, payload: MaterialIgnoreRequest, db: Annotated[Session, Depends(get_db)]) -> PageRead:
    if db.get(CanvasPage, page_id) is None:
        raise HTTPException(status_code=404, detail="Onbekende pagina")
    return page_read_for(db, set_page_ignored(db, page_id, payload.ignored))


@router.post("/items/{item_id}/sheet", response_model=AssignmentTextResponse)
def fetch_sheet(
    item_id: str, payload: AssignmentTextRequest, db: Annotated[Session, Depends(get_db)]
) -> AssignmentTextResponse:
    """De opgave van een opdracht zonder pdf als markdown in het corpus."""
    if db.get(CanvasItem, item_id) is None:
        raise HTTPException(status_code=404, detail="Onbekend item")
    client = _client()
    if client is None:
        raise to_http_exception(CanvasNotConfigured())
    try:
        document, chunk_count = fetch_assignment_text(db, client, item_id, overwrite=payload.overwrite)
    except Exception as exc:  # noqa: BLE001 — vertaald naar een HTTP-status
        raise to_http_exception(exc) from exc
    return AssignmentTextResponse(document=DocumentRead.model_validate(document), chunk_count=chunk_count)


@router.post("/tasks", response_model=TaskRead, status_code=201)
def create_task(payload: TaskCreate, db: Annotated[Session, Depends(get_db)]) -> TaskRead:
    task = Task(
        title=payload.title,
        notes=payload.notes,
        due_on=payload.due_on,
        course_slug=payload.course_slug,
        link=payload.link,
        links=[link.model_dump() for link in payload.links],
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task_read(task, _now())


def _live_task(db: Session, task_id: str) -> Task:
    """Een zacht verwijderde taak bestaat nog wel, maar telt nergens meer mee."""
    task = db.get(Task, task_id)
    if task is None or task.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Onbekende taak")
    return task


@router.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(task_id: str, payload: TaskUpdate, db: Annotated[Session, Depends(get_db)]) -> TaskRead:
    task = _live_task(db, task_id)
    # Alleen wat er in het verzoek stond: `due_on: null` wist de datum,
    # een verzoek zonder due_on laat hem staan.
    given = payload.model_fields_set
    for name in ("title", "notes", "due_on", "course_slug", "link"):
        if name in given:
            setattr(task, name, getattr(payload, name))
    if "links" in given:
        task.links = [link.model_dump() for link in payload.links or []]
    now = _now()
    if "done" in given:
        task.done_at = (task.done_at or now) if payload.done else None
    db.commit()
    return task_read(task, now)


@router.delete("/tasks/{task_id}", response_model=TaskRead)
def delete_task(task_id: str, db: Annotated[Session, Depends(get_db)]) -> TaskRead:
    task = _live_task(db, task_id)
    now = _now()
    task.deleted_at = now
    db.commit()
    return task_read(task, now)


@router.post("/tasks/{task_id}/restore", response_model=TaskRead)
def restore_task(task_id: str, db: Annotated[Session, Depends(get_db)]) -> TaskRead:
    """Het "ongedaan maken" achter Verwijder. Zelfde id, zelfde created_at:
    opnieuw aanmaken zou een andere taak opleveren."""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Onbekende taak")
    task.deleted_at = None
    db.commit()
    return task_read(task, _now())
