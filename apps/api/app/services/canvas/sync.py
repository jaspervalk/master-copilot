"""De momentopname van Canvas in de database.

Eerst alles ophalen, dan pas schrijven, in één transactie: een 401 of een
netwerkfout halverwege laat de vorige momentopname staan. Wat Canvas
beheert wordt overschreven; wat van de gebruiker is (`hidden`, `done_at`,
`unmarked_at`, `ignored_at`, `document_id`) blijft met rust. Items en bestanden die Canvas
niet meer noemt verdwijnen: Canvas is de bron.

Vooraf worden de course.yml's opnieuw gelezen. Zo werkt een nieuwe
`canvas_id` zonder `python -m app.cli sync` (dat de Qdrant-lock nodig heeft),
en klapt een verstreken deadline hier ook om naar `closed` — de agenda is de
plek waar je dat hoort te merken.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CanvasAnnouncement, CanvasCourse, CanvasFile, CanvasItem, CanvasPage, utcnow
from app.services.canvas.client import CanvasClient, CanvasError, file_ids_in_html, parse_timestamp, strip_html
from app.services.corpus_sync import parse_course_config, recompute_assignment_status, upsert_course_from_yaml


DESCRIPTION_MAX_CHARS = 4000
# Het venster van de planner: kalenderitems en vinkjes. Opdrachten en quizzen
# komen los per vak, dus hier hoeft niet het hele jaar in.
PLANNER_LOOKBACK = timedelta(days=90)
PLANNER_LOOKAHEAD = timedelta(days=200)
# "Final Exam" en "Retake exam". Niet "final": het Data Systems Project heeft
# een "Final report", en dat is geen tentamen.
_EXAM_NAME_RE = re.compile(r"\b(exam|tentamen)\b", re.IGNORECASE)
_SUBMISSION_KEYS = ("workflow_state", "submitted_at", "score", "grade", "late", "missing", "excused", "attempt")


@dataclass
class CanvasSyncReport:
    courses: int = 0
    items: int = 0
    announcements: int = 0
    files_seen: int = 0
    files_new: int = 0
    removed: int = 0
    # (vak, wat er aan course.yml mankeert) — dezelfde regels als bij `sync`.
    course_problems: list[tuple[str, str]] = field(default_factory=list)
    # (pad, waarom) — een hulpendpoint dat een student niet mag zien.
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def as_lines(self) -> list[str]:
        lines = [
            f"vakken: {self.courses}",
            f"items: {self.items}",
            f"aankondigingen: {self.announcements}",
            f"materiaal: {self.files_seen}",
            f"nieuw materiaal: {self.files_new}",
            f"verwijderd: {self.removed}",
        ]
        for slug, problem in self.course_problems:
            lines.append(f"course.yml  {slug}: {problem}")
        for path, reason in self.skipped:
            lines.append(f"overgeslagen {path}: {reason}")
        return lines


@dataclass
class _CourseSnapshot:
    course: dict
    assignments: list[dict] = field(default_factory=list)
    # (quiz, eigen inzending of None)
    quizzes: list[tuple[dict, dict | None]] = field(default_factory=list)
    announcements: list[dict] = field(default_factory=list)
    # bestand-id → {source, module_name, assignment_item_id}: de eerste plek
    # waar de link stond.
    file_refs: dict[int, dict] = field(default_factory=dict)
    folders: dict[int, str] = field(default_factory=dict)
    # page_url → {title, module_name, updated_at}: de pagina's uit de modules.
    pages: dict[str, dict] = field(default_factory=dict)
    # Alleen een geoogst vak mag bestanden kwijtraken. Zonder oogst (geen
    # canvas_id, even een fout in course.yml) weten we niets over zijn bestanden,
    # en zouden de negeer- en ophaalvlaggen verdwijnen.
    harvested: bool = False


# --- course.yml -------------------------------------------------------------


def _course_dirs(corpus_root: Path) -> list[Path]:
    if not corpus_root.is_dir():
        return []
    return sorted(
        path for path in corpus_root.iterdir()
        if path.is_dir() and not path.name.startswith(".") and (path / "course.yml").exists()
    )


def refresh_course_rows(db: Session, corpus_root: Path, *, today: date | None = None) -> list[tuple[str, str]]:
    """Lees elke course.yml opnieuw en herbereken de opdrachtstatus."""
    problems: list[tuple[str, str]] = []
    for path in _course_dirs(corpus_root):
        _, course_problems = upsert_course_from_yaml(db, path.name, corpus_root)
        problems.extend((path.name, problem) for problem in course_problems)
        recompute_assignment_status(db, path.name, today=today)
    return problems


def _mapped_canvas_ids(corpus_root: Path) -> set[int]:
    """Uit de bestanden zelf, niet uit de database: zo klopt het ook bij een
    dry-run, die niets schrijft."""
    ids: set[int] = set()
    for path in _course_dirs(corpus_root):
        config = parse_course_config((path / "course.yml").read_text(encoding="utf-8"))
        if config.canvas_id is not None:
            ids.add(config.canvas_id)
    return ids


# --- ophalen ----------------------------------------------------------------


def _optional(client: CanvasClient, path: str, params: dict | None, report: CanvasSyncReport) -> Any | None:
    """403 is het melden waard (er is iets wat je niet mag zien); 404 is
    gewoon een vak zonder quizzen of voorpagina."""
    try:
        return client.get(path, params)
    except CanvasError as exc:
        if exc.status == 403:
            report.skipped.append((path, "403, niet toegankelijk"))
            return None
        if exc.status == 404:
            return None
        raise


def classify_assignment(assignment: dict) -> str:
    types = assignment.get("submission_types") or []
    if "on_paper" in types or _EXAM_NAME_RE.search(assignment.get("name") or ""):
        return "exam"
    return "assignment"


def _folder_name(full_name: str | None) -> str | None:
    name = (full_name or "").removeprefix("course files").strip("/")
    return name or None


def _fetch_course(client: CanvasClient, course: dict, *, mapped: bool, report: CanvasSyncReport) -> _CourseSnapshot:
    cid = course["id"]
    snapshot = _CourseSnapshot(course)
    snapshot.assignments = client.get(f"courses/{cid}/assignments", {"include[]": ["submission"]})
    for quiz in _optional(client, f"courses/{cid}/quizzes", None, report) or []:
        submissions = _optional(client, f"courses/{cid}/quizzes/{quiz['id']}/submissions", None, report) or {}
        own = (submissions.get("quiz_submissions") or [None])[0]
        snapshot.quizzes.append((quiz, own))
    snapshot.announcements = client.get(f"courses/{cid}/discussion_topics", {"only_announcements": "true"})
    if mapped:
        _harvest_files(client, snapshot, report)
    return snapshot


def _harvest_files(client: CanvasClient, snapshot: _CourseSnapshot, report: CanvasSyncReport) -> None:
    """Waar bestanden te vinden zijn: module-items, en links in pagina's,
    opdrachten, aankondigingen, de syllabus en de voorpagina. De mappenlijst
    is zichtbaar, de mapinhoud niet — vandaar deze omweg."""
    cid = snapshot.course["id"]
    snapshot.harvested = True

    def note(file_id: int, **context: Any) -> None:
        snapshot.file_refs.setdefault(file_id, context)

    folders = _optional(client, f"courses/{cid}/folders", None, report) or []
    snapshot.folders = {folder["id"]: name for folder in folders if (name := _folder_name(folder.get("full_name")))}

    for module in _optional(client, f"courses/{cid}/modules", {"include[]": ["items"]}, report) or []:
        for item in module.get("items") or []:
            if item.get("type") == "File" and item.get("content_id"):
                note(int(item["content_id"]), source=f"module:{module['name']}", module_name=module["name"])
            elif item.get("type") == "Page" and item.get("page_url"):
                page = _optional(client, f"courses/{cid}/pages/{item['page_url']}", None, report) or {}
                title = page.get("title") or item.get("title") or item["page_url"]
                if page:
                    snapshot.pages.setdefault(
                        item["page_url"],
                        {"title": title, "module_name": module["name"], "updated_at": page.get("updated_at")},
                    )
                for file_id in file_ids_in_html(page.get("body")):
                    note(file_id, source=f"page:{item.get('title') or item['page_url']}", module_name=module["name"])

    for assignment in snapshot.assignments:
        for file_id in file_ids_in_html(assignment.get("description")):
            note(file_id, source=f"assignment:{assignment.get('name') or ''}", assignment_item_id=f"assignment:{assignment['id']}")
    for announcement in snapshot.announcements:
        for file_id in file_ids_in_html(announcement.get("message")):
            note(file_id, source=f"announcement:{announcement.get('title') or ''}")

    detail = _optional(client, f"courses/{cid}", {"include[]": ["syllabus_body"]}, report) or {}
    for file_id in file_ids_in_html(detail.get("syllabus_body")):
        note(file_id, source="syllabus")
    front_page = _optional(client, f"courses/{cid}/front_page", None, report) or {}
    for file_id in file_ids_in_html(front_page.get("body")):
        note(file_id, source="front_page")


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_planner(client: CanvasClient, now: datetime, course_ids: set[int]) -> tuple[dict[str, bool], list[tuple[int, dict]]]:
    """Het vinkje dat je in Canvas zet, en de kalenderitems (spreekuren)."""
    items = client.get(
        "planner/items",
        {"start_date": _iso(now - PLANNER_LOOKBACK), "end_date": _iso(now + PLANNER_LOOKAHEAD)},
    )
    overrides: dict[str, bool] = {}
    events: list[tuple[int, dict]] = []
    for item in items:
        cid = item.get("course_id")
        if cid not in course_ids:
            continue
        kind = item.get("plannable_type")
        if kind == "calendar_event":
            events.append((cid, item))
        elif kind in ("assignment", "quiz") and (item.get("planner_override") or {}).get("marked_complete"):
            overrides[f"{kind}:{item['plannable_id']}"] = True
    return overrides, events


# --- rijen ------------------------------------------------------------------


def _submission(raw: dict | None) -> dict:
    if not raw:
        return {}
    return {key: raw.get(key) for key in _SUBMISSION_KEYS if key in raw}


def _assignment_values(assignment: dict, overrides: dict[str, bool], now: datetime) -> dict:
    key = f"assignment:{assignment['id']}"
    return {
        "id": key,
        "kind": classify_assignment(assignment),
        "title": assignment.get("name") or "",
        "description": strip_html(assignment.get("description"))[:DESCRIPTION_MAX_CHARS],
        "html_url": assignment.get("html_url"),
        "due_at": parse_timestamp(assignment.get("due_at")),
        "unlock_at": parse_timestamp(assignment.get("unlock_at")),
        "lock_at": parse_timestamp(assignment.get("lock_at")),
        "answers_at": None,
        "points_possible": assignment.get("points_possible"),
        "submission_types": list(assignment.get("submission_types") or []),
        "submission": _submission(assignment.get("submission")),
        "marked_complete": overrides.get(key, False),
        "fetched_at": now,
    }


def _quiz_values(quiz: dict, own: dict | None, overrides: dict[str, bool], now: datetime) -> dict:
    key = f"quiz:{quiz['id']}"
    submission = {}
    if own:
        submission = {
            "workflow_state": own.get("workflow_state"),
            "score": own.get("score"),
            "attempt": own.get("attempt"),
            "finished_at": own.get("finished_at"),
            "submitted_at": own.get("finished_at"),
        }
    return {
        "id": key,
        "kind": "quiz",
        "title": quiz.get("title") or "",
        "description": strip_html(quiz.get("description"))[:DESCRIPTION_MAX_CHARS],
        "html_url": quiz.get("html_url"),
        "due_at": parse_timestamp(quiz.get("due_at")),
        "unlock_at": parse_timestamp(quiz.get("unlock_at")),
        "lock_at": parse_timestamp(quiz.get("lock_at")),
        "answers_at": parse_timestamp(quiz.get("show_correct_answers_at")),
        "points_possible": quiz.get("points_possible"),
        "submission_types": [],
        "submission": submission,
        "marked_complete": overrides.get(key, False),
        "fetched_at": now,
    }


def _event_values(item: dict, now: datetime) -> dict:
    plannable = item.get("plannable") or {}
    return {
        "id": f"event:{item['plannable_id']}",
        "kind": "event",
        "title": plannable.get("title") or "",
        "description": "",
        "html_url": item.get("html_url"),
        "due_at": parse_timestamp(plannable.get("start_at") or item.get("plannable_date")),
        "unlock_at": None,
        "lock_at": parse_timestamp(plannable.get("end_at")),
        "answers_at": None,
        "points_possible": None,
        "submission_types": [],
        "submission": {},
        "marked_complete": False,
        "fetched_at": now,
    }


def _upsert_item(db: Session, cid: int, values: dict) -> str:
    row = db.get(CanvasItem, values["id"])
    if row is None:
        row = CanvasItem(canvas_course_id=cid, **values)
        db.add(row)
    else:
        row.canvas_course_id = cid
        # Zet Canvas het vinkje opnieuw aan, dan vervalt jouw terugzetting:
        # Canvas spreekt opnieuw. Moet vóór het overschrijven, anders is de
        # oude waarde weg.
        if values.get("marked_complete") and not row.marked_complete:
            row.unmarked_at = None
        for key, value in values.items():
            setattr(row, key, value)
    return values["id"]


def _upsert_announcement(db: Session, cid: int, announcement: dict, now: datetime) -> int:
    row = db.get(CanvasAnnouncement, announcement["id"])
    if row is None:
        row = CanvasAnnouncement(id=announcement["id"], canvas_course_id=cid, title="")
        db.add(row)
    row.canvas_course_id = cid
    row.title = announcement.get("title") or ""
    row.posted_at = parse_timestamp(announcement.get("posted_at"))
    row.body = strip_html(announcement.get("message"))
    row.html_url = announcement.get("html_url")
    row.read_state = announcement.get("read_state")
    row.fetched_at = now
    return row.id


def _upsert_file(db: Session, snapshot: _CourseSnapshot, file_id: int, meta: dict | None, now: datetime) -> None:
    context = snapshot.file_refs[file_id]
    row = db.get(CanvasFile, file_id)
    if row is None:
        if meta is None:
            return
        row = CanvasFile(
            id=file_id,
            canvas_course_id=snapshot.course["id"],
            filename=meta.get("filename") or meta.get("display_name") or str(file_id),
            display_name=meta.get("display_name") or meta.get("filename") or str(file_id),
            size=meta.get("size"),
            content_type=meta.get("content-type") or meta.get("content_type"),
            folder=snapshot.folders.get(meta.get("folder_id")),
            module_name=context.get("module_name"),
            source=context.get("source") or "",
            assignment_item_id=context.get("assignment_item_id"),
            updated_at=parse_timestamp(meta.get("updated_at")),
        )
        db.add(row)
    row.fetched_at = now


def _upsert_page(db: Session, cid: int, page_url: str, values: dict, now: datetime) -> str:
    page_id = f"{cid}:{page_url}"
    row = db.get(CanvasPage, page_id)
    if row is None:
        row = CanvasPage(id=page_id, canvas_course_id=cid, page_url=page_url, title="")
        db.add(row)
    row.title = values["title"]
    row.module_name = values.get("module_name")
    row.updated_at = parse_timestamp(values.get("updated_at"))
    row.fetched_at = now
    return page_id


def _write(
    db: Session,
    courses: list[dict],
    snapshots: dict[int, _CourseSnapshot],
    overrides: dict[str, bool],
    events: list[tuple[int, dict]],
    file_meta: dict[int, dict | None],
    now: datetime,
    report: CanvasSyncReport,
) -> None:
    for course in courses:
        cid = course["id"]
        row = db.get(CanvasCourse, cid)
        if row is None:
            row = CanvasCourse(id=cid, name="")
            db.add(row)
        row.name = course.get("name") or str(cid)
        row.course_code = course.get("course_code")
        row.term = (course.get("term") or {}).get("name")
        row.fetched_at = now

    for cid, snapshot in snapshots.items():
        item_ids = {_upsert_item(db, cid, _assignment_values(a, overrides, now)) for a in snapshot.assignments}
        item_ids |= {_upsert_item(db, cid, _quiz_values(quiz, own, overrides, now)) for quiz, own in snapshot.quizzes}
        item_ids |= {_upsert_item(db, cid, _event_values(item, now)) for event_cid, item in events if event_cid == cid}
        announcement_ids = {_upsert_announcement(db, cid, a, now) for a in snapshot.announcements}
        for file_id in snapshot.file_refs:
            _upsert_file(db, snapshot, file_id, file_meta.get(file_id), now)
        page_ids = {_upsert_page(db, cid, page_url, values, now) for page_url, values in snapshot.pages.items()}

        db.flush()
        stale = [
            delete(CanvasItem).where(CanvasItem.canvas_course_id == cid, CanvasItem.id.not_in(item_ids)),
            delete(CanvasAnnouncement).where(
                CanvasAnnouncement.canvas_course_id == cid, CanvasAnnouncement.id.not_in(announcement_ids)
            ),
        ]
        if snapshot.harvested:
            stale.append(
                delete(CanvasFile).where(CanvasFile.canvas_course_id == cid, CanvasFile.id.not_in(snapshot.file_refs))
            )
            stale.append(delete(CanvasPage).where(CanvasPage.canvas_course_id == cid, CanvasPage.id.not_in(page_ids)))
        for statement in stale:
            report.removed += db.execute(statement).rowcount

    db.commit()


# --- de sync ----------------------------------------------------------------


def sync_canvas(
    db: Session,
    client: CanvasClient,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
    corpus_root: Path | None = None,
) -> CanvasSyncReport:
    now = now or utcnow()
    corpus_root = corpus_root or settings.corpus_dir
    report = CanvasSyncReport()

    if not dry_run:
        report.course_problems = refresh_course_rows(db, corpus_root, today=now.date())
    mapped = _mapped_canvas_ids(corpus_root)
    hidden = set(db.scalars(select(CanvasCourse.id).where(CanvasCourse.hidden.is_(True))))
    known_files = set(db.scalars(select(CanvasFile.id)))

    courses = client.get("courses", {"enrollment_state": "active", "include[]": ["term"]})
    report.courses = len(courses)
    snapshots = {
        course["id"]: _fetch_course(client, course, mapped=course["id"] in mapped, report=report)
        for course in courses
        if course["id"] not in hidden
    }
    overrides, events = _fetch_planner(client, now, set(snapshots))

    # Alleen onbekende bestanden opvragen: de eerste keer zijn het er tientallen,
    # daarna een handvol.
    file_meta: dict[int, dict | None] = {}
    for snapshot in snapshots.values():
        for file_id in snapshot.file_refs:
            if file_id not in known_files and file_id not in file_meta:
                file_meta[file_id] = _optional(client, f"files/{file_id}", None, report)

    report.items = sum(len(s.assignments) + len(s.quizzes) for s in snapshots.values()) + len(events)
    report.announcements = sum(len(s.announcements) for s in snapshots.values())
    report.files_seen = sum(len(s.file_refs) for s in snapshots.values())
    report.files_new = sum(1 for meta in file_meta.values() if meta is not None)

    if dry_run:
        return report
    _write(db, courses, snapshots, overrides, events, file_meta, now, report)
    return report
