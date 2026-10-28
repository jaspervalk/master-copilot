"""Breng de database in overeenstemming met wat er in `corpus/` staat.

Idempotent: twee keer draaien verandert niets. De sha256 van het bestand bepaalt
of er opnieuw geïndexeerd moet worden.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Course, Document
from app.services.documents import delete_document, index_document, mark_document_failed
from app.services.path_metadata import (
    SUPPORTED_SUFFIXES,
    CorpusPath,
    CorpusPathError,
    parse_corpus_path,
)
from app.services.practice.exams import import_course_exams
from app.services.storage import checksum_of_file


logger = logging.getLogger(__name__)

_IGNORED_DIRECTORIES = {".trash", ".git", "__MACOSX"}


@dataclass
class SyncReport:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    removed: int = 0
    # (relatief pad, foutmelding)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    # (vak, wat er aan course.yml mankeert)
    course_problems: list[tuple[str, str]] = field(default_factory=list)
    # Tentamentranscripties in exams/: wat er geïmporteerd is, en welke
    # geweigerd zijn omdat het antwoordmodel niet klopt.
    exam_imports: list[str] = field(default_factory=list)
    exam_problems: list[tuple[str, str]] = field(default_factory=list)

    def as_lines(self) -> list[str]:
        lines = [
            f"toegevoegd: {self.added}",
            f"bijgewerkt: {self.updated}",
            f"ongewijzigd: {self.skipped}",
            f"verwijderd: {self.removed}",
        ]
        for path, reason in self.rejected:
            lines.append(f"geweigerd   {path}: {reason}")
        for path, reason in self.failed:
            lines.append(f"mislukt     {path}: {reason}")
        for course_slug, reason in self.course_problems:
            lines.append(f"course.yml  {course_slug}: {reason}")
        for line in self.exam_imports:
            lines.append(f"tentamen    {line}")
        for path, reason in self.exam_problems:
            lines.append(f"tentamen    {path}: {reason}")
        return lines


def scan_corpus(corpus_root: Path) -> tuple[list[CorpusPath], list[tuple[str, str]]]:
    found: list[CorpusPath] = []
    rejected: list[tuple[str, str]] = []

    for path in sorted(corpus_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(corpus_root)
        if any(part in _IGNORED_DIRECTORIES for part in relative.parts):
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        # Een README legt de mappen uit en is geen stof; corpus/README.md zou
        # anders bij elke sync als pad zonder vak geweigerd worden.
        if path.name.lower() == "readme.md":
            continue
        try:
            found.append(parse_corpus_path(path, corpus_root))
        except CorpusPathError as exc:
            rejected.append((relative.as_posix(), str(exc)))

    return found, rejected


# Wat een mens schrijft als hij een deadline bedoelt. `deadline` is de
# gedocumenteerde vorm; de rest kost niets om te accepteren.
_DEADLINE_KEYS = ("deadline", "due_date", "due")
_KNOWN_TOP_LEVEL_KEYS = frozenset(
    {"name", "period", "lecturer", "assignments", "weeks", "canvas_id", "exams", "study"}
)

# Wat er onder `study:` mag staan: hoe het tentamen naar code vraagt, en
# waarvoor je leert (`assessment`, één zin). Een gesloten verzameling, zoals
# overal hier — een typefout hoort een melding te geven en niet stil te
# verdwijnen.
_KNOWN_STUDY_KEYS = frozenset({"code", "assessment"})

# none: geen code op het tentamen. read: je krijgt een fragment en voorspelt de
# uitvoer, maar hoeft geen syntax uit je hoofd te schrijven. Zonder instelling
# mag alles. Twee waarden en geen boolean, omdat SSO precies het middengeval
# bleek: de docent van deel 2 zei bij college 8 dat "wat is de uitvoer" op het
# tentamen kan komen, en dat je een vergeten komma niet wordt aangerekend.
CODE_SETTINGS = frozenset({"none", "read"})


@dataclass
class CourseConfig:
    """Wat er uit course.yml te halen viel, plus wat eraan mankeerde.

    De problemen worden teruggegeven in plaats van weggelogd: een verkeerde
    deadline zet een uitwerking te vroeg open, dus dat hoort in het
    sync-rapport te staan en niet in een regel die je mist.
    """

    name: str | None = None
    period: str | None = None
    lecturer: str | None = None
    # Hoe dit vak getoetst wordt, voor zover dat het studeren stuurt.
    # `{"code": "read"}`: fragmenten lezen en de uitvoer voorspellen.
    study: dict = field(default_factory=dict)
    deadlines: dict[str, str] = field(default_factory=dict)
    # week (als string) → {lectures, topics, reading}. De koppeling tussen een
    # week en de hoofdstukken die erbij horen; zonder dit bereikt een
    # weekfilter alleen slides, want een boek heeft geen week.
    week_plans: dict[str, dict] = field(default_factory=dict)
    # Dezelfde opdrachten als `deadlines`, maar mét naam en punten:
    # [{name, week, due_date, available_date, points}]. De agenda vergelijkt
    # per naam met Canvas; de spoilerfilter blijft op `deadlines` draaien.
    assignments: list[dict] = field(default_factory=list)
    # Het Canvas-id van het vak, en tentamens die niet als Canvas-opdracht
    # bestaan: [{name, date}].
    canvas_id: int | None = None
    exams: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _first_deadline_value(entry: dict):
    for key in _DEADLINE_KEYS:
        if entry.get(key) is not None:
            return entry[key]
    return None


def parse_course_config(raw_text: str) -> CourseConfig:
    """Lees course.yml. Onbekende velden zijn welkom en worden genegeerd."""
    config = CourseConfig()
    try:
        data = yaml.safe_load(raw_text) or {}
    except yaml.YAMLError as exc:
        config.problems.append(f"onleesbare YAML: {' '.join(str(exc).split())[:160]}")
        return config
    if not isinstance(data, dict):
        config.problems.append("de inhoud is geen sleutel-waardelijst")
        return config

    config.name = str(data["name"]) if data.get("name") else None
    config.period = str(data["period"]) if data.get("period") else None
    config.lecturer = str(data["lecturer"]) if data.get("lecturer") else None

    raw_canvas_id = data.get("canvas_id")
    if raw_canvas_id is not None:
        try:
            config.canvas_id = int(raw_canvas_id)
        except (TypeError, ValueError):
            config.problems.append(f"canvas_id moet een getal zijn, niet {raw_canvas_id!r}")

    _parse_assignments(data, config)
    _parse_exams(data, config)
    _parse_weeks(data, config)

    study = data.get("study")
    if study is not None:
        if not isinstance(study, dict):
            config.problems.append("'study' moet een blok met instellingen zijn")
        else:
            for key, value in study.items():
                if key == "no_code":
                    # Stond één dag in SSO's course.yml; zeg wat het nu heet.
                    config.problems.append("'no_code' bestaat niet meer; schrijf 'code: none' (of 'code: read')")
                elif key not in _KNOWN_STUDY_KEYS:
                    config.problems.append(f"onbekende sleutel '{key}' onder 'study'")
                elif key == "assessment":
                    if not isinstance(value, str) or not value.strip():
                        config.problems.append("'assessment' onder 'study' moet één zin zijn: waarvoor je leert")
                    else:
                        config.study[key] = value.strip()
                elif str(value) not in CODE_SETTINGS:
                    config.problems.append(
                        f"'code: {value}' onder 'study' kan niet; kies uit {', '.join(sorted(CODE_SETTINGS))}"
                    )
                else:
                    config.study[key] = str(value)

    near_miss = [key for key in data if key not in _KNOWN_TOP_LEVEL_KEYS]
    for key in near_miss:
        hint = "assignments" if "assign" in str(key).lower() else "weeks" if "week" in str(key).lower() else None
        if hint and hint not in data:
            config.problems.append(f"onbekende sleutel '{key}'; bedoelde je '{hint}'?")

    return config


def _parse_assignments(data: dict, config: CourseConfig) -> None:
    entries = data.get("assignments")
    if entries is None:
        return
    if not isinstance(entries, list):
        config.problems.append("'assignments' moet een lijst zijn")
        return

    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            config.problems.append(f"opdracht {index} is geen sleutel-waardelijst")
            continue

        label = entry.get("name") or f"opdracht {index}"
        week = entry.get("week")
        raw_deadline = _first_deadline_value(entry)

        # Een regel zonder allebei is een aantekening — een tentamen bijvoorbeeld.
        if week is None and raw_deadline is None:
            continue
        if week is None:
            config.problems.append(f"'{label}' heeft geen week en kan dus niet aan een opdracht gekoppeld worden")
            continue
        if raw_deadline is None:
            config.problems.append(f"'{label}' heeft geen deadline (gebruik 'deadline' of 'due_date')")
            continue

        try:
            parsed = date.fromisoformat(str(raw_deadline))
            config.deadlines[str(int(week))] = parsed.isoformat()
        except (TypeError, ValueError):
            config.problems.append(
                f"'{label}': week={week!r} deadline={raw_deadline!r} is geen geldige datum (jjjj-mm-dd)"
            )
            continue

        config.assignments.append(
            {
                "name": str(label),
                "week": int(week),
                "due_date": parsed.isoformat(),
                "available_date": _optional_date(entry.get("available_date"), f"'{label}': available_date", config),
                "points": _optional_number(entry.get("points"), f"'{label}': points", config),
            }
        )


def _optional_date(raw, label: str, config: CourseConfig) -> str | None:
    if raw is None:
        return None
    try:
        return date.fromisoformat(str(raw)).isoformat()
    except (TypeError, ValueError):
        config.problems.append(f"{label}={raw!r} is geen geldige datum (jjjj-mm-dd)")
        return None


def _optional_number(raw, label: str, config: CourseConfig) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        config.problems.append(f"{label}={raw!r} is geen getal")
        return None


def _parse_exams(data: dict, config: CourseConfig) -> None:
    """`exams: [{name, date}]` — voor een tentamen dat niet als Canvas-opdracht
    bestaat. Alleen de agenda kijkt hiernaar; de spoilerfilter niet."""
    entries = data.get("exams")
    if entries is None:
        return
    if not isinstance(entries, list):
        config.problems.append("'exams' moet een lijst zijn")
        return

    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            config.problems.append(f"tentamen {index} is geen sleutel-waardelijst")
            continue
        label = entry.get("name") or f"tentamen {index}"
        raw_date = entry.get("date")
        if raw_date is None:
            config.problems.append(f"'{label}' heeft geen date (jjjj-mm-dd)")
            continue
        try:
            parsed = date.fromisoformat(str(raw_date))
        except (TypeError, ValueError):
            config.problems.append(f"'{label}': date={raw_date!r} is geen geldige datum (jjjj-mm-dd)")
            continue
        config.exams.append({"name": str(label), "date": parsed.isoformat()})


def _parse_reading(entry: dict, label: str, config: CourseConfig) -> dict | None:
    document = entry.get("document") or entry.get("source_path")
    if not document:
        config.problems.append(f"{label}: een leesregel heeft 'document' nodig (het pad binnen corpus/)")
        return None

    sections = entry.get("sections") or []
    if isinstance(sections, str):
        sections = [sections]
    sections = [str(section).strip() for section in sections if str(section).strip()]

    pages = entry.get("pages")
    if pages is not None:
        try:
            first, last = (int(pages), int(pages)) if isinstance(pages, int) else (int(pages[0]), int(pages[1]))
            if first > last:
                raise ValueError
            pages = [first, last]
        except (TypeError, ValueError, IndexError):
            config.problems.append(f"{label}: pages={pages!r} moet één getal of [begin, eind] zijn")
            return None

    return {"document": str(document), "sections": sections, "pages": pages}


def _parse_weeks(data: dict, config: CourseConfig) -> None:
    """`weeks: [{week, lectures, topics, reading}]`.

    Zonder deze koppeling bereikt een weekfilter alleen slides en opgaven: een
    boek hoort bij het hele vak en heeft dus geen week. Hiermee weet het
    systeem dat week 2 van SSO over Triola 9.2-9.4 gaat en niet over de rest
    van het boek.
    """
    entries = data.get("weeks")
    if entries is None:
        return
    if not isinstance(entries, list):
        config.problems.append("'weeks' moet een lijst zijn")
        return

    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            config.problems.append(f"week {index} is geen sleutel-waardelijst")
            continue

        week = entry.get("week")
        try:
            week_key = str(int(week))
        except (TypeError, ValueError):
            config.problems.append(f"week {index}: 'week' ontbreekt of is geen getal ({week!r})")
            continue

        label = f"week {week_key}"
        raw_reading = entry.get("reading") or []
        if isinstance(raw_reading, dict):
            raw_reading = [raw_reading]
        if not isinstance(raw_reading, list):
            config.problems.append(f"{label}: 'reading' moet een lijst zijn")
            continue

        reading = [
            parsed
            for item in raw_reading
            if isinstance(item, dict) and (parsed := _parse_reading(item, label, config)) is not None
        ]
        topics = entry.get("topics") or []
        if isinstance(topics, str):
            topics = [topics]

        config.week_plans[week_key] = {
            "lectures": [int(n) for n in (entry.get("lectures") or []) if str(n).lstrip("-").isdigit()],
            "topics": [str(topic) for topic in topics],
            "reading": reading,
        }


def upsert_course_from_yaml(db: Session, course_slug: str, corpus_root: Path) -> tuple[Course, list[str]]:
    """Geef het vak terug, plus wat er aan zijn course.yml mankeerde."""
    course = db.get(Course, course_slug)
    if course is None:
        course = Course(slug=course_slug, name=course_slug.replace("-", " ").title())
        db.add(course)

    problems: list[str] = []
    config_path = corpus_root / course_slug / "course.yml"
    if config_path.exists():
        config = parse_course_config(config_path.read_text(encoding="utf-8"))
        problems = config.problems
        course.name = config.name or course.name
        course.period = config.period or course.period
        course.lecturer = config.lecturer or course.lecturer
        course.deadlines = config.deadlines
        course.week_plans = config.week_plans
        course.canvas_id = config.canvas_id
        course.assignments = config.assignments
        course.exams = config.exams
        course.study = config.study
        for problem in problems:
            logger.warning("course.yml van %s: %s", course_slug, problem)

    db.commit()
    return course, problems


def recompute_assignment_status(db: Session, course_slug: str, today: date | None = None) -> int:
    """closed na de deadline, anders submitted bij een inzending, anders open.

    De deadline wint van de inzending: bij groepswerk levert een teamgenoot in
    en staat er hier nooit een bestand, maar dicht is dicht. Zonder deadline
    hoeft er niets bijgehouden te worden: je zet je uitwerking in
    submissions/week-NN/ en de status volgt vanzelf.
    """
    today = today or date.today()
    course = db.get(Course, course_slug)
    deadlines = (course.deadlines if course else None) or {}

    submitted_weeks = {
        week
        for (week,) in db.execute(
            select(Document.week).where(
                Document.course_slug == course_slug,
                Document.doc_kind == "submission",
            )
        )
    }

    changed = 0
    assignments = db.scalars(
        select(Document).where(
            Document.course_slug == course_slug,
            Document.doc_kind == "assignment",
        )
    ).all()
    for assignment in assignments:
        deadline = deadlines.get(str(assignment.week)) if assignment.week is not None else None
        if deadline and date.fromisoformat(deadline) < today:
            status = "closed"
        elif assignment.week in submitted_weeks:
            status = "submitted"
        else:
            status = "open"
        if assignment.assignment_status != status:
            assignment.assignment_status = status
            changed += 1

    if changed:
        db.commit()
    return changed


def sync_corpus(db: Session, *, course_slug: str | None = None, dry_run: bool = False) -> SyncReport:
    corpus_root = settings.corpus_dir
    found, rejected = scan_corpus(corpus_root)
    if course_slug:
        found = [item for item in found if item.course_slug == course_slug]
        rejected = [item for item in rejected if item[0].startswith(f"{course_slug}/")]

    report = SyncReport(rejected=rejected)
    seen_paths: set[str] = set()
    touched_courses: set[str] = set()

    for entry in found:
        seen_paths.add(entry.relative_path)
        touched_courses.add(entry.course_slug)
        checksum = checksum_of_file(entry.absolute_path)
        existing = db.scalar(select(Document).where(Document.source_path == entry.relative_path))

        if existing is not None and existing.checksum == checksum and existing.ingestion_status == "indexed":
            report.skipped += 1
            continue

        if dry_run:
            if existing is None:
                report.added += 1
            else:
                report.updated += 1
            continue

        if existing is None:
            document = Document(
                title=entry.absolute_path.stem.replace("-", " ").replace("_", " ").strip(),
                source_path=entry.relative_path,
                checksum=checksum,
                course_slug=entry.course_slug,
                doc_kind=entry.doc_kind,
                week=entry.week,
            )
            db.add(document)
            db.commit()
            is_new = True
        else:
            document = existing
            document.checksum = checksum
            document.course_slug = entry.course_slug
            document.doc_kind = entry.doc_kind
            document.week = entry.week
            db.commit()
            is_new = False

        try:
            index_document(db, document)
        except Exception as exc:  # noqa: BLE001 — één kapot bestand stopt de run niet
            mark_document_failed(db, document, str(exc))
            report.failed.append((entry.relative_path, str(exc)))
            continue

        if is_new:
            report.added += 1
        else:
            report.updated += 1

    if not dry_run:
        stmt = select(Document)
        if course_slug:
            stmt = stmt.where(Document.course_slug == course_slug)
        for document in db.scalars(stmt).all():
            if document.source_path in seen_paths:
                continue
            # Het bestand is weg; de rij en de vectoren horen dan ook weg. Niet
            # naar de prullenbak: er is niets meer om te verplaatsen.
            delete_document(db, document, trash=False)
            report.removed += 1

        for slug in sorted(touched_courses):
            _, problems = upsert_course_from_yaml(db, slug, corpus_root)
            report.course_problems.extend((slug, problem) for problem in problems)
            recompute_assignment_status(db, slug)
            # Na de documenten: een tentamenkaart verwijst naar de chunk van de
            # PDF op dezelfde pagina, en die bestaat pas na het indexeren.
            for result in import_course_exams(db, slug, corpus_root):
                if result.problems:
                    report.exam_problems.append((result.path, "; ".join(result.problems)))
                else:
                    report.exam_imports.append(result.as_line())

    return report
