"""Het leesmodel van de agendapagina.

Alles wat een datum heeft in één lijst — Canvas-items en tentamens uit
course.yml — met een status, een bucket (vandaag, deze week, …) en de
doorlinks naar de rest van de app. Per vak daarnaast: de tentamens, de
copilot-toestand (herhalen, oefententamens, weken zonder samenvatting), de
aankondigingen en de verschillen tussen course.yml en Canvas.

Tijd: de database is naïef UTC; hier krijgt alles `timezone.utc` mee zodat
pydantic een `Z` schrijft en de browser lokaal rendert. Buckets worden hier
berekend, in Europe/Amsterdam, zodat een test `now` kan vastzetten — en
omdat "vandaag" een kalenderdag is, geen UTC-dag.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    CanvasAnnouncement,
    CanvasCourse,
    CanvasFile,
    CanvasItem,
    CanvasPage,
    Course,
    Document,
    Task,
    WeekSummary,
    utcnow,
)
from app.schemas import (
    AgendaAnnouncementRead,
    AgendaCanvasState,
    AgendaCopilotRead,
    AgendaCourseRead,
    AgendaDiffRead,
    AgendaExamRead,
    AgendaItemRead,
    AgendaQuizRead,
    AgendaRead,
    AgendaYamlLink,
    ExamSetRead,
    MaterialPlacementRead,
    MaterialRead,
    PageRead,
    TaskRead,
)
from app.services.canvas.client import client_from_settings, parse_timestamp
from app.services.canvas.placement import (
    Proposal,
    corpus_basename,
    material_state,
    normalize_name,
    page_state,
    propose_page,
    propose_placement,
)
from app.services.corpus_sync import parse_course_config
from app.services.practice.exams import exam_progress
from app.services.practice.scheduling import due_cards
from app.services.weeks_summary import is_stale

__all__ = ["build_agenda", "bucket_for", "derive_status", "local_date", "normalize_name", "item_read_for", "material_read_for", "page_read_for", "task_read", "utc"]


AMSTERDAM = ZoneInfo("Europe/Amsterdam")
ANNOUNCEMENTS_PER_COURSE = 10
DESCRIPTION_PREVIEW_CHARS = 600
# Statussen waarna een item niets meer van je vraagt.
FINISHED = frozenset({"graded", "submitted", "late", "done", "closed", "past"})
# Statussen waarna het vinkje geen betekenis meer heeft. Bewust een ándere
# verzameling dan FINISHED: `done` is afgerond, maar juist wél terug te draaien.
SETTLED = frozenset({"graded", "submitted", "late", "closed", "past"})


# --- tijd -------------------------------------------------------------------


def utc(moment: datetime | None) -> datetime | None:
    return None if moment is None else moment.replace(tzinfo=timezone.utc)


def local_date(moment: datetime) -> date:
    """De Amsterdamse kalenderdag van een naïef-UTC-moment: 21:59Z is vandaag,
    22:30Z is morgen."""
    return moment.replace(tzinfo=timezone.utc).astimezone(AMSTERDAM).date()


# --- status en bucket -------------------------------------------------------


def _is_done(item: CanvasItem) -> bool:
    """Afgevinkt hier, of in Canvas zonder dat je het hier terugzette."""
    return bool(item.done_at) or (bool(item.marked_complete) and item.unmarked_at is None)


def derive_status(item: CanvasItem, now: datetime) -> str:
    submission = item.submission or {}
    if item.kind == "event":
        end = item.lock_at or item.due_at
        return "past" if end is not None and end < now else "upcoming"
    if item.kind == "quiz":
        if submission.get("workflow_state") == "complete" or submission.get("finished_at"):
            return "graded"
        if _is_done(item):
            return "done"
        if item.lock_at and item.lock_at < now:
            return "closed"
        if item.unlock_at and item.unlock_at > now:
            return "locked"
        return "open"
    if submission.get("workflow_state") == "graded":
        return "graded"
    if submission.get("submitted_at"):
        return "late" if submission.get("late") else "submitted"
    if _is_done(item):
        return "done"
    if item.kind == "exam":
        # Canvas zet unlock_at gelijk aan due_at; "nog niet open" en "te laat"
        # zeggen niets over een tentamen.
        return "past" if item.due_at and item.due_at < now else "upcoming"
    if submission.get("missing"):
        return "missing"
    if item.lock_at and item.lock_at < now:
        return "closed"
    if item.due_at and item.due_at < now:
        return "overdue"
    if item.unlock_at and item.unlock_at > now:
        return "locked"
    return "open"


def bucket_for(deadline: datetime | date | None, *, now: datetime, finished: bool) -> str:
    if finished:
        return "done"
    if deadline is None:
        return "undated"
    today = local_date(now)
    if isinstance(deadline, datetime):
        if deadline < now:
            return "overdue"
        day = local_date(deadline)
    else:
        day = deadline
        if day < today:
            return "overdue"
    if day == today:
        return "today"
    if day == today + timedelta(days=1):
        return "tomorrow"
    if day.isocalendar()[:2] == today.isocalendar()[:2]:
        return "this_week"
    if day.isocalendar()[:2] == (today + timedelta(days=7)).isocalendar()[:2]:
        return "next_week"
    return "later"


def place_for(
    deadline: datetime | date | None, *, now: datetime, finished: bool, finished_on: date | None = None
) -> str:
    """Waar een rij in de lijst staat. `bucket_for` zegt wat hij betekent
    (afgerond telt niet meer mee in de navigatiebalk); dit zegt waar je hem ziet.

    Een afgevinkte rij blijft op zijn dag staan, met vinkje, tot die dag voorbij
    is. Eerst ging hij na tien seconden naar een ingeklapte strip, en dan was
    voor wie hem afvinkte ook weg wat hij gedaan had. Een afgevinkte deadline
    van vanochtend hoort bij vandaag: hier telt de kalenderdag, niet het uur.
    Is de dag voorbij, dan staat hij nog een week bij Verlopen, met vinkje, op
    datum tussen de rest van de afgelopen dagen — ook als je hem pas vandaag
    afvinkte (`finished_on`). Pas daarna bij Afgerond. Afgerond onderaan was te
    ver weg (de taken van dinsdag stonden donderdag onder alles van volgende
    week), en een apart blok Gedaan zag je evenmin: ze horen bij Verlopen.
    """
    if not finished:
        return bucket_for(deadline, now=now, finished=False)
    if deadline is None:
        return "undated"
    today = local_date(now)
    day = local_date(deadline) if isinstance(deadline, datetime) else deadline
    if day >= today:
        return bucket_for(day, now=now, finished=False)
    # De laatste van de twee: wie gisteren een oude taak afvinkte, deed hem gisteren.
    done_on = max(day, finished_on) if finished_on is not None else day
    if done_on >= today - timedelta(days=RECENT_DAYS):
        return "overdue"
    return "done"


# Zo lang blijft wat je afrondde bij Verlopen staan.
RECENT_DAYS = 7


def _day_of(moment: datetime | None) -> date | None:
    return None if moment is None else local_date(moment)


def _days_left(day: date | None, now: datetime) -> int | None:
    return None if day is None else (day - local_date(now)).days


# --- de context van één vak -------------------------------------------------


@dataclass
class _CourseContext:
    canvas: CanvasCourse | None
    course: Course | None
    items: list[CanvasItem] = field(default_factory=list)
    # week → id van het open opgavenblad; en de weken waar überhaupt een
    # opgavenblad staat.
    open_sheets: dict[int, str] = field(default_factory=dict)
    sheet_weeks: set[int] = field(default_factory=set)
    # Canvas-item → bestand dat bij die opdracht hing (het opgavenblad).
    files_by_item: dict[str, int] = field(default_factory=dict)

    @property
    def slug(self) -> str | None:
        return self.course.slug if self.course else None

    @property
    def name(self) -> str:
        if self.canvas is not None:
            return self.canvas.name
        return self.course.name if self.course else ""

    @property
    def canvas_id(self) -> int | None:
        return self.canvas.id if self.canvas else None

    @property
    def yaml_assignments(self) -> list[dict]:
        return list((self.course.assignments if self.course else None) or [])

    def yaml_for(self, item: CanvasItem) -> dict | None:
        wanted = normalize_name(item.title)
        return next((entry for entry in self.yaml_assignments if normalize_name(entry.get("name")) == wanted), None)


def _contexts(db: Session) -> list[_CourseContext]:
    canvas_courses = {row.id: row for row in db.scalars(select(CanvasCourse))}
    courses = list(db.scalars(select(Course)))
    by_canvas_id = {course.canvas_id: course for course in courses if course.canvas_id is not None}

    contexts: list[_CourseContext] = []
    for canvas_id, canvas in canvas_courses.items():
        contexts.append(_CourseContext(canvas=canvas, course=by_canvas_id.get(canvas_id)))
    for course in courses:
        if course.canvas_id not in canvas_courses:
            contexts.append(_CourseContext(canvas=None, course=course))

    by_canvas = {context.canvas_id: context for context in contexts if context.canvas is not None}
    for item in db.scalars(select(CanvasItem)):
        if item.canvas_course_id in by_canvas:
            by_canvas[item.canvas_course_id].items.append(item)
    for file in db.scalars(select(CanvasFile).where(CanvasFile.assignment_item_id.is_not(None))):
        context = by_canvas.get(file.canvas_course_id)
        if context is not None and file.filename.lower().endswith(".pdf"):
            context.files_by_item.setdefault(file.assignment_item_id, file.id)

    by_slug = {context.slug: context for context in contexts if context.slug}
    sheets = db.execute(
        select(Document.course_slug, Document.week, Document.assignment_status, Document.id).where(
            Document.doc_kind == "assignment", Document.week.is_not(None)
        )
    )
    for slug, week, status, document_id in sheets:
        context = by_slug.get(slug)
        if context is None:
            continue
        context.sheet_weeks.add(week)
        if status == "open":
            context.open_sheets.setdefault(week, document_id)
    return sorted(contexts, key=lambda context: context.name.lower())


# --- items ------------------------------------------------------------------


def _item_read(item: CanvasItem, context: _CourseContext, now: datetime) -> AgendaItemRead:
    submission = item.submission or {}
    status = derive_status(item, now)
    deadline = item.due_at or item.lock_at
    yaml = None
    coach_document_id = None
    if item.kind == "assignment" and (entry := context.yaml_for(item)) is not None:
        due_date = date.fromisoformat(entry["due_date"])
        yaml = AgendaYamlLink(
            name=entry["name"],
            week=int(entry["week"]),
            due_date=due_date,
            same_day=item.due_at is not None and local_date(item.due_at) == due_date,
        )
        coach_document_id = context.open_sheets.get(int(entry["week"]))
    quiz = None
    if item.kind == "quiz":
        quiz = AgendaQuizRead(
            attempt=submission.get("attempt"),
            score=submission.get("score"),
            finished_at=utc(parse_timestamp(submission.get("finished_at"))),
            answers_at=utc(item.answers_at),
        )
    return AgendaItemRead(
        id=item.id,
        kind=item.kind,
        course_id=item.canvas_course_id,
        course_slug=context.slug,
        course_name=context.name,
        title=item.title,
        html_url=item.html_url,
        description=(item.description or "")[:DESCRIPTION_PREVIEW_CHARS],
        due_at=utc(item.due_at),
        unlock_at=utc(item.unlock_at),
        lock_at=utc(item.lock_at),
        deadline_at=utc(deadline),
        days_left=_days_left(local_date(deadline) if deadline else None, now),
        points_possible=item.points_possible,
        submission_types=list(item.submission_types or []),
        status=status,
        bucket=bucket_for(deadline, now=now, finished=status in FINISHED),
        place=place_for(
            deadline,
            now=now,
            finished=status in FINISHED,
            # Je eigen vinkje, of anders het moment van inleveren.
            finished_on=_day_of(item.done_at or parse_timestamp(submission.get("submitted_at"))),
        ),
        score=submission.get("score"),
        grade=submission.get("grade"),
        submitted_at=utc(parse_timestamp(submission.get("submitted_at"))),
        late=bool(submission.get("late")),
        missing=bool(submission.get("missing")),
        marked_complete=bool(item.marked_complete),
        done_at=utc(item.done_at),
        tickable=status not in SETTLED,
        quiz=quiz,
        yaml=yaml,
        coach_document_id=coach_document_id,
    )


def _yaml_exam_item(context: _CourseContext, index: int, entry: dict, now: datetime) -> AgendaItemRead:
    """Een tentamen dat alleen in course.yml staat (SSO). Een dag, geen tijd."""
    day = date.fromisoformat(entry["date"])
    status = "past" if day < local_date(now) else "upcoming"
    return AgendaItemRead(
        id=f"exam:{context.slug}:{index}",
        kind="exam",
        course_id=context.canvas_id,
        course_slug=context.slug,
        course_name=context.name,
        title=entry["name"],
        due_on=day,
        days_left=_days_left(day, now),
        status=status,
        bucket=bucket_for(day, now=now, finished=status in FINISHED),
        place=place_for(day, now=now, finished=status in FINISHED),
    )


def _sort_key(item: AgendaItemRead) -> tuple:
    if item.deadline_at is not None:
        return (0, item.deadline_at.replace(tzinfo=None), item.title)
    if item.due_on is not None:
        return (0, datetime.combine(item.due_on, time(12, 0)), item.title)
    return (1, datetime.max, item.title)


# --- tentamens en verschillen ------------------------------------------------


def _exams(context: _CourseContext, now: datetime) -> tuple[list[AgendaExamRead], list[AgendaItemRead], list[AgendaDiffRead]]:
    canvas_exams = [item for item in context.items if item.kind == "exam"]
    yaml_exams = list((context.course.exams if context.course else None) or [])
    reads: list[AgendaExamRead] = []
    extra_items: list[AgendaItemRead] = []
    diffs: list[AgendaDiffRead] = []
    matched: set[str] = set()
    unmatched_yaml: list[dict] = []

    for index, entry in enumerate(yaml_exams):
        day = date.fromisoformat(entry["date"])
        match = next(
            (exam for exam in canvas_exams if exam.id not in matched and exam.due_at and local_date(exam.due_at) == day),
            None,
        )
        if match is not None:
            matched.add(match.id)
            reads.append(AgendaExamRead(name=entry["name"], date=day, days_left=_days_left(day, now), source="both", canvas_item_id=match.id))
        else:
            unmatched_yaml.append(entry)
            reads.append(AgendaExamRead(name=entry["name"], date=day, days_left=_days_left(day, now), source="yaml", canvas_item_id=None))
            extra_items.append(_yaml_exam_item(context, index, entry, now))

    leftover = [exam for exam in canvas_exams if exam.id not in matched]
    for exam in leftover:
        day = local_date(exam.due_at) if exam.due_at else None
        reads.append(AgendaExamRead(name=exam.title, date=day, days_left=_days_left(day, now), source="canvas", canvas_item_id=exam.id))

    if context.course is not None:
        for entry, exam in zip(unmatched_yaml, leftover):
            canvas_day = local_date(exam.due_at).isoformat() if exam.due_at else "zonder datum"
            diffs.append(
                AgendaDiffRead(
                    kind="exam_date_differs",
                    message=f"{entry['name']}: course.yml zegt {entry['date']}, Canvas '{exam.title}' {canvas_day}",
                    item_id=exam.id,
                )
            )
        if not yaml_exams and canvas_exams:
            for exam in canvas_exams:
                diffs.append(
                    AgendaDiffRead(
                        kind="exam_missing_in_yaml",
                        message=f"'{exam.title}' staat in Canvas maar niet onder exams: in course.yml",
                        item_id=exam.id,
                    )
                )
    return reads, extra_items, diffs


def _assignment_diffs(context: _CourseContext) -> list[AgendaDiffRead]:
    """course.yml tegenover Canvas, alleen ter melding: de deadline in
    course.yml stuurt de spoilerfilter en wordt hier nooit aangepast."""
    if context.course is None:
        return []
    diffs: list[AgendaDiffRead] = []
    assignments = [item for item in context.items if item.kind == "assignment"]
    matched: set[str] = set()
    for entry in context.yaml_assignments:
        name = entry.get("name") or "?"
        week = int(entry["week"])
        wanted = normalize_name(name)
        match = next((item for item in assignments if normalize_name(item.title) == wanted), None)
        if match is None:
            if context.canvas is not None:
                diffs.append(AgendaDiffRead(kind="yaml_only", message=f"'{name}' uit course.yml staat niet in Canvas", week=week))
        else:
            matched.add(match.id)
            if match.due_at is not None and local_date(match.due_at).isoformat() != entry["due_date"]:
                diffs.append(
                    AgendaDiffRead(
                        kind="due_date_differs",
                        message=(
                            f"{name}: course.yml zegt {entry['due_date']}, Canvas {local_date(match.due_at).isoformat()} — "
                            "pas course.yml aan als Canvas gelijk heeft"
                        ),
                        item_id=match.id,
                        week=week,
                    )
                )
        if week not in context.sheet_weeks:
            file_id = context.files_by_item.get(match.id) if match else None
            diffs.append(
                AgendaDiffRead(
                    kind="assignment_sheet_missing",
                    message=f"Opgavenblad van '{name}' staat niet in het corpus (assignments/week-{week:02d})",
                    item_id=match.id if match else None,
                    week=week,
                    file_id=file_id,
                    # Geen pdf bij de opdracht, wel een beschrijving: dan ís die
                    # beschrijving de opgave (zo werkt FDS).
                    can_fetch_text=match is not None and file_id is None and bool(match.description),
                )
            )
    for item in assignments:
        if item.id not in matched and item.due_at is not None:
            diffs.append(
                AgendaDiffRead(
                    kind="canvas_only",
                    message=(
                        f"'{item.title}' (Canvas, {local_date(item.due_at).isoformat()}) staat niet in course.yml — "
                        "de spoilerfilter kent hem niet"
                    ),
                    item_id=item.id,
                )
            )
    return diffs


# --- copilot, aankondigingen, taken -------------------------------------------


def _copilot(db: Session, context: _CourseContext) -> AgendaCopilotRead | None:
    if context.course is None:
        return None
    slug = context.course.slug
    planned = {int(key) for key in (context.course.week_plans or {})}
    summaries = list(db.scalars(select(WeekSummary).where(WeekSummary.course_slug == slug)))
    return AgendaCopilotRead(
        due_count=len(due_cards(db, slug)),
        exam_sets=[ExamSetRead.from_progress(exam) for exam in exam_progress(db, slug)],
        weeks_without_summary=sorted(planned - {summary.week for summary in summaries}),
        # Een vingerafdruk per week herberekenen kost enkele tientallen
        # milliseconden; de agenda wordt geladen, niet gepolld.
        stale_summaries=sorted(summary.week for summary in summaries if is_stale(db, summary)),
    )


def _announcements(db: Session, context: _CourseContext) -> list[AgendaAnnouncementRead]:
    if context.canvas is None:
        return []
    rows = db.scalars(
        select(CanvasAnnouncement)
        .where(CanvasAnnouncement.canvas_course_id == context.canvas.id)
        .order_by(CanvasAnnouncement.posted_at.desc())
        .limit(ANNOUNCEMENTS_PER_COURSE)
    )
    return [
        AgendaAnnouncementRead(
            id=row.id, title=row.title, posted_at=utc(row.posted_at), body=row.body,
            html_url=row.html_url, unread=row.read_state == "unread",
        )
        for row in rows
    ]


# Nieuw en onzeker eerst: daar moet je iets mee. Wat er al staat of wat je
# wegklikte komt onderaan.
_STATE_ORDER = {"new": 0, "unplaced": 1, "unsupported": 2, "in_corpus": 3, "downloaded": 4, "ignored": 5}


def _material_read(file: CanvasFile, proposal: Proposal, existing: Document | None) -> MaterialRead:
    placement = proposal.placement
    return MaterialRead(
        id=file.id,
        canvas_course_id=file.canvas_course_id,
        filename=file.filename,
        display_name=file.display_name,
        size=file.size,
        content_type=file.content_type,
        folder=file.folder,
        module_name=file.module_name,
        source=file.source or "",
        updated_at=utc(file.updated_at),
        state=material_state(file, proposal, existing),
        placement=(
            MaterialPlacementRead(doc_kind=placement.doc_kind, week=placement.week, relative_path=placement.relative_path)
            if placement
            else None
        ),
        reason=proposal.reason,
        document_id=file.document_id,
        corpus_path=file.corpus_path,
    )


def _corpus_names(db: Session, slug: str) -> dict[str, Document]:
    """Bestandsnaam in het corpus → document, om te zien wat er al staat."""
    return {Path(doc.source_path).name.lower(): doc for doc in db.scalars(select(Document).where(Document.course_slug == slug))}


def _materials(db: Session, context: _CourseContext, corpus_root: Path) -> list[MaterialRead]:
    if context.course is None or context.canvas is None:
        return []
    names = _corpus_names(db, context.course.slug)
    files = db.scalars(select(CanvasFile).where(CanvasFile.canvas_course_id == context.canvas.id))
    reads = [
        _material_read(file, propose_placement(file, context.course, corpus_root=corpus_root), names.get(corpus_basename(file.filename)))
        for file in files
    ]
    return sorted(reads, key=lambda read: (_STATE_ORDER[read.state], read.module_name or "", read.filename.lower()))


def material_read_for(db: Session, file: CanvasFile, *, corpus_root: Path | None = None) -> MaterialRead:
    """Eén bestand opnieuw uitrekenen, na ophalen of negeren."""
    corpus_root = corpus_root or settings.corpus_dir
    course = db.scalar(select(Course).where(Course.canvas_id == file.canvas_course_id))
    if course is None:
        return _material_read(file, Proposal(None, "dit vak heeft geen corpus (canvas_id ontbreekt in course.yml)"), None)
    existing = _corpus_names(db, course.slug).get(corpus_basename(file.filename))
    return _material_read(file, propose_placement(file, course, corpus_root=corpus_root), existing)


def _page_read(page: CanvasPage, proposal: Proposal, existing: Document | None) -> PageRead:
    placement = proposal.placement
    return PageRead(
        id=page.id,
        canvas_course_id=page.canvas_course_id,
        title=page.title,
        module_name=page.module_name,
        updated_at=utc(page.updated_at),
        state=page_state(page, existing),
        placement=(
            MaterialPlacementRead(doc_kind=placement.doc_kind, week=placement.week, relative_path=placement.relative_path)
            if placement
            else None
        ),
        reason=proposal.reason,
        document_id=page.document_id,
    )


def _page_reads(db: Session, course: Course, pages: list[CanvasPage], corpus_root: Path) -> list[PageRead]:
    names = _corpus_names(db, course.slug)
    reads = []
    for page in pages:
        # Een pagina krijgt altijd een plek; wat daar al staat, bepaalt de staat.
        proposal = propose_page(page, course, corpus_root=corpus_root)
        existing = names.get(Path(proposal.placement.relative_path).name.lower())
        reads.append(_page_read(page, proposal, existing))
    return reads


def _pages(db: Session, context: _CourseContext, corpus_root: Path) -> list[PageRead]:
    if context.course is None or context.canvas is None:
        return []
    pages = list(db.scalars(select(CanvasPage).where(CanvasPage.canvas_course_id == context.canvas.id)))
    order = {"new": 0, "in_corpus": 1, "downloaded": 2, "ignored": 3}
    return sorted(
        _page_reads(db, context.course, pages, corpus_root),
        key=lambda read: (order[read.state], read.module_name or "", read.title.lower()),
    )


def page_read_for(db: Session, page: CanvasPage, *, corpus_root: Path | None = None) -> PageRead:
    """Eén pagina opnieuw uitrekenen, na ophalen of negeren."""
    corpus_root = corpus_root or settings.corpus_dir
    course = db.scalar(select(Course).where(Course.canvas_id == page.canvas_course_id))
    if course is None:
        return _page_read(page, Proposal(None, "dit vak heeft geen corpus (canvas_id ontbreekt in course.yml)"), None)
    return _page_reads(db, course, [page], corpus_root)[0]


def task_read(task: Task, now: datetime) -> TaskRead:
    return TaskRead(
        id=task.id,
        title=task.title,
        notes=task.notes or "",
        due_on=task.due_on,
        course_slug=task.course_slug,
        link=task.link,
        # Taken van vóór de kolom hebben NULL in de database.
        links=task.links or [],
        done_at=utc(task.done_at),
        created_at=utc(task.created_at),
        bucket=bucket_for(task.due_on, now=now, finished=task.done_at is not None),
        place=place_for(task.due_on, now=now, finished=task.done_at is not None, finished_on=_day_of(task.done_at)),
    )


def _tasks(db: Session, now: datetime, hidden_slugs: set[str] = frozenset()) -> list[TaskRead]:
    # Een verborgen vak doe je niet meer; je studietaken ervoor horen dan net
    # zo min onder Verlopen als zijn deadlines. Terug met "toon".
    rows = [
        task
        for task in db.scalars(select(Task).where(Task.deleted_at.is_(None)))
        if task.course_slug not in hidden_slugs
    ]
    open_tasks = sorted(
        (task for task in rows if task.done_at is None),
        key=lambda task: (task.due_on is None, task.due_on or date.max, task.created_at or datetime.min),
    )
    done_tasks = sorted((task for task in rows if task.done_at is not None), key=lambda task: task.done_at, reverse=True)
    return [task_read(task, now) for task in open_tasks + done_tasks]


def _course_problems(corpus_root: Path) -> list[str]:
    if not corpus_root.is_dir():
        return []
    problems: list[str] = []
    for path in sorted(corpus_root.iterdir()):
        config_path = path / "course.yml"
        if path.name.startswith(".") or not config_path.exists():
            continue
        config = parse_course_config(config_path.read_text(encoding="utf-8"))
        problems.extend(f"course.yml {path.name}: {problem}" for problem in config.problems)
    return problems


# --- het geheel ---------------------------------------------------------------


def item_read_for(db: Session, item: CanvasItem, *, now: datetime | None = None) -> AgendaItemRead:
    """Eén item opnieuw uitrekenen, bijvoorbeeld na een vinkje."""
    now = now or utcnow()
    context = next(
        (context for context in _contexts(db) if context.canvas_id == item.canvas_course_id),
        _CourseContext(canvas=None, course=None),
    )
    return _item_read(item, context, now)


def build_agenda(
    db: Session,
    *,
    now: datetime | None = None,
    corpus_root: Path | None = None,
    configured: bool | None = None,
) -> AgendaRead:
    now = now or utcnow()
    corpus_root = corpus_root or settings.corpus_dir
    if configured is None:
        configured = client_from_settings() is not None
    contexts = _contexts(db)

    courses: list[AgendaCourseRead] = []
    items: list[AgendaItemRead] = []
    hidden_slugs = {context.slug for context in contexts if context.slug and context.canvas and context.canvas.hidden}
    for context in contexts:
        exams, extra_items, exam_diffs = _exams(context, now)
        course_items = [_item_read(item, context, now) for item in context.items] + extra_items
        hidden = bool(context.canvas.hidden) if context.canvas else False
        if not hidden:
            items.extend(course_items)
        diffs = exam_diffs + _assignment_diffs(context)
        if context.course is not None and context.canvas is None:
            diffs.append(
                AgendaDiffRead(
                    kind="canvas_id_missing",
                    message=f"Zet canvas_id in corpus/{context.course.slug}/course.yml om dit vak aan Canvas te koppelen",
                )
            )
        courses.append(
            AgendaCourseRead(
                canvas_id=context.canvas_id,
                course_slug=context.slug,
                name=context.name,
                course_code=context.canvas.course_code if context.canvas else None,
                term=context.canvas.term if context.canvas else None,
                hidden=hidden,
                fetched_at=utc(context.canvas.fetched_at) if context.canvas else None,
                item_count=len(course_items),
                exams=exams,
                copilot=_copilot(db, context),
                announcements=_announcements(db, context),
                diffs=diffs,
                materials=_materials(db, context, corpus_root),
                pages=_pages(db, context, corpus_root),
            )
        )

    fetched = [context.canvas.fetched_at for context in contexts if context.canvas and context.canvas.fetched_at]
    synced_at = max(fetched) if fetched else None
    stale = synced_at is None or now - synced_at > timedelta(minutes=settings.canvas_stale_after_minutes)

    return AgendaRead(
        now=utc(now),
        canvas=AgendaCanvasState(configured=configured, synced_at=utc(synced_at), stale=stale),
        courses=courses,
        items=sorted(items, key=_sort_key),
        tasks=_tasks(db, now, hidden_slugs),
        problems=_course_problems(corpus_root),
    )
