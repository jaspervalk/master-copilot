"""Materiaal van Canvas in het corpus zetten — door hetzelfde ingestpad als
uploaden, zodat het precies belandt waar `sync` het ook zou vinden."""
from __future__ import annotations

from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CanvasCourse, CanvasFile, CanvasItem, CanvasPage, Course, Document, utcnow
from app.services.canvas.client import CanvasClient, CanvasError, html_to_markdown, parse_timestamp
from app.services.canvas.placement import clean_filename, normalize_name, propose_page, propose_placement
from app.services.documents import ingest_bytes
from app.services.path_metadata import DOC_KINDS

AMSTERDAM = ZoneInfo("Europe/Amsterdam")


# Soorten die zonder week niet werken: slides vallen dan buiten elke weekkaart
# en weekfilter, een opgavenblad heeft zonder week geen status.
WEEK_REQUIRED_KINDS = ("slides", "assignment")


def course_for_file(db: Session, file: CanvasFile) -> Course | None:
    return db.scalar(select(Course).where(Course.canvas_id == file.canvas_course_id))


def fetch_material(
    db: Session,
    client: CanvasClient,
    file_id: int,
    *,
    doc_kind: str | None = None,
    week: int | None = None,
    overwrite: bool = False,
    corpus_root: Path | None = None,
) -> tuple[CanvasFile, Document, int]:
    """Download en indexeer. De keuze van de gebruiker (`doc_kind`, `week`)
    gaat vóór het voorstel; zonder allebei wordt er niets geraden."""
    corpus_root = corpus_root or settings.corpus_dir
    file = db.get(CanvasFile, file_id)
    if file is None:
        raise ValueError("Onbekend Canvas-bestand")
    course = course_for_file(db, file)
    if course is None:
        raise ValueError("Dit vak heeft geen corpus: zet canvas_id in course.yml om er materiaal in te zetten")

    proposal = propose_placement(file, course, corpus_root=corpus_root)
    if proposal.unsupported:
        raise ValueError(proposal.reason)
    if doc_kind is not None:
        if doc_kind not in DOC_KINDS:
            raise ValueError(f"Onbekend documentsoort '{doc_kind}'")
        if doc_kind in WEEK_REQUIRED_KINDS and week is None:
            raise ValueError(f"Kies een week: {doc_kind} zonder week valt buiten elke weekkaart en weekfilter")
        kind, target_week = doc_kind, week
    elif proposal.placement is not None:
        kind, target_week = proposal.placement.doc_kind, proposal.placement.week
    else:
        raise ValueError(f"Geen plek voorgesteld ({proposal.reason}): kies soort en week")

    # De download-URL wordt elke keer opnieuw gelezen: hij draagt een
    # verifier-geheim en verloopt.
    meta = client.get(f"files/{file_id}")
    url = meta.get("url") if isinstance(meta, dict) else None
    if not url:
        raise CanvasError(None, f"files/{file_id}", "geen download-URL in het antwoord")
    content = client.download(url, max_bytes=settings.max_upload_size_bytes)

    document, chunk_count, _, _ = ingest_bytes(
        db,
        content=content,
        filename=clean_filename(file.filename),
        course_slug=course.slug,
        doc_kind=kind,
        week=target_week,
        overwrite=overwrite,
    )
    file.document_id = document.id
    file.corpus_path = document.source_path
    db.commit()
    return file, document, chunk_count


def _format_points(points: float | None) -> str | None:
    if points is None:
        return None
    return str(int(points)) if float(points).is_integer() else str(points).replace(".", ",")


def fetch_assignment_text(
    db: Session,
    client: CanvasClient,
    item_id: str,
    *,
    overwrite: bool = False,
) -> tuple[Document, int]:
    """Zet de opgave van een Canvas-opdracht als markdown in het corpus.

    Voor een opdracht zonder pdf: bij FDS ís de beschrijving in Canvas de
    opgave, en zonder die tekst in het corpus kan de coach er niet bij. De week
    komt uit course.yml, op naam; zonder regel daar wordt er niets geplaatst."""
    item = db.get(CanvasItem, item_id)
    if item is None:
        raise ValueError("Onbekend item")
    if item.kind != "assignment":
        raise ValueError("Alleen een opdracht heeft een opgave om op te halen")
    course = db.scalar(select(Course).where(Course.canvas_id == item.canvas_course_id))
    if course is None:
        raise ValueError("Dit vak heeft geen corpus: zet canvas_id in course.yml")
    wanted = normalize_name(item.title)
    entry = next((row for row in course.assignments or [] if normalize_name(row.get("name")) == wanted), None)
    if entry is None:
        raise ValueError(f"'{item.title}' staat niet in course.yml, dus de week is onbekend")

    # Vers uit Canvas: de beschrijving in de momentopname is ingekort, en een
    # docent past een opgave soms nog aan.
    assignment = client.get(f"courses/{item.canvas_course_id}/assignments/{item_id.split(':', 1)[1]}")
    body = html_to_markdown(assignment.get("description"))
    if not body:
        raise ValueError("Canvas heeft voor deze opdracht geen beschrijving")

    canvas_course = db.get(CanvasCourse, item.canvas_course_id)
    due = parse_timestamp(assignment.get("due_at"))
    facts = [
        ("Vak", canvas_course.name if canvas_course else course.name),
        ("Deadline", due.replace(tzinfo=timezone.utc).astimezone(AMSTERDAM).strftime("%Y-%m-%d %H:%M") if due else None),
        ("Punten", _format_points(assignment.get("points_possible"))),
        ("Canvas", assignment.get("html_url")),
    ]
    header = "\n".join(f"- {label}: {value}" for label, value in facts if value)
    content = f"# {entry['name']}\n\n{header}\n\n{body}\n"

    document, chunk_count, _, _ = ingest_bytes(
        db,
        content=content.encode("utf-8"),
        filename=f"{entry['name']}.md",
        course_slug=course.slug,
        doc_kind="assignment",
        week=int(entry["week"]),
        overwrite=overwrite,
    )
    return document, chunk_count


def fetch_page(
    db: Session,
    client: CanvasClient,
    page_id: str,
    *,
    overwrite: bool = False,
    corpus_root: Path | None = None,
) -> tuple[CanvasPage, Document, int]:
    """Een modulepagina als markdown in het corpus, op zijn voorgestelde plek."""
    corpus_root = corpus_root or settings.corpus_dir
    page = db.get(CanvasPage, page_id)
    if page is None:
        raise ValueError("Onbekende pagina")
    course = db.scalar(select(Course).where(Course.canvas_id == page.canvas_course_id))
    if course is None:
        raise ValueError("Dit vak heeft geen corpus: zet canvas_id in course.yml")
    placement = propose_page(page, course, corpus_root=corpus_root).placement

    data = client.get(f"courses/{page.canvas_course_id}/pages/{page.page_url}")
    body = html_to_markdown(data.get("body"))
    if not body:
        raise ValueError("Deze pagina heeft geen tekst om in het corpus te zetten")
    canvas_course = db.get(CanvasCourse, page.canvas_course_id)
    facts = [("Vak", canvas_course.name if canvas_course else course.name), ("Canvas", data.get("html_url"))]
    header = "\n".join(f"- {label}: {value}" for label, value in facts if value)
    content = f"# {page.title}\n\n{header}\n\n{body}\n"

    document, chunk_count, _, _ = ingest_bytes(
        db,
        content=content.encode("utf-8"),
        filename=f"{page.title}.md",
        course_slug=course.slug,
        doc_kind=placement.doc_kind,
        week=placement.week,
        overwrite=overwrite,
    )
    page.document_id = document.id
    db.commit()
    return page, document, chunk_count


def set_page_ignored(db: Session, page_id: str, ignored: bool) -> CanvasPage:
    page = db.get(CanvasPage, page_id)
    if page is None:
        raise ValueError("Onbekende pagina")
    page.ignored_at = utcnow() if ignored else None
    db.commit()
    return page


def set_ignored(db: Session, file_id: int, ignored: bool) -> CanvasFile:
    file = db.get(CanvasFile, file_id)
    if file is None:
        raise ValueError("Onbekend Canvas-bestand")
    file.ignored_at = utcnow() if ignored else None
    db.commit()
    return file
