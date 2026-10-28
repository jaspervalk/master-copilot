"""Waar een Canvas-bestand in het corpus hoort.

Een voorstel, geen besluit: de gebruiker haalt het op, of kiest zelf soort
en week. De regels lezen de bestandsnaam, de Canvas-map en de module, en
course.yml (`lectures:`, het leesplan, de opdrachten). Wat niet zeker is
krijgt een reden en geen plek — raden zet een uitwerking in de verkeerde
week of een handout tussen de papers.

Het voorstel wordt bij het lezen berekend en niet opgeslagen: zodra
course.yml een week `lectures: [5, 6]` krijgt, is lecture5.pdf plaatsbaar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from app.models import CanvasFile, CanvasPage, Course, Document
from app.services.path_metadata import SUPPORTED_SUFFIXES, build_corpus_path, sanitize_filename


@dataclass(frozen=True)
class Placement:
    doc_kind: str
    week: int | None
    relative_path: str


@dataclass(frozen=True)
class Proposal:
    placement: Placement | None
    # Altijd gevuld: het bewijs, of waarom er geen plek is.
    reason: str
    unsupported: bool = False


# Niet midden in een woord: "reflect2.pdf" is geen college 2.
_LECTURE_RE = re.compile(r"(?<![a-z])lect(?:ure)?[_\- ]?0*(\d+)", re.IGNORECASE)
_LECTURE_FOLDER_RE = re.compile(r"lecture\s*0*(\d+)", re.IGNORECASE)
_WEEK_RE = re.compile(r"\bweek\s*0*(\d+)", re.IGNORECASE)
_SECTION_RE = re.compile(r"^section[+ _]?(\d+(?:\.\d+)?)", re.IGNORECASE)
_ASSIGNMENT_RE = re.compile(r"(?:assign(?:ment)?|opdracht|homework)\s*[_\- ]?0*(\d+)?", re.IGNORECASE)
_YEAR_PREFIX_RE = re.compile(r"^((?:19|20)\d{2})[-_ ]")
_ET_AL_RE = re.compile(r"\bet[-_ ]al\b", re.IGNORECASE)
_LITERATURE_RE = re.compile(r"reading|paper|literature|article", re.IGNORECASE)
# Een uitwerking wordt nooit voorgesteld: als opgavenblad of oefening zou hij
# buiten de spoilerfilter vallen, die alleen solutions/ en submissions/ kent.
_SOLUTION_RE = re.compile(
    r"(?<![a-z])(?:sol|solutions?|uitwerking(?:en)?|answers?|antwoorden)(?![a-z])", re.IGNORECASE
)
# Een (oud) tentamen. Ook een herkansing: zonder "resit" kreeg het voorblad van
# de SSO-herkansing van 2022 geen plek.
_EXAM_RE = re.compile(r"exam|tentamen|mock|resit|herkansing", re.IGNORECASE)
# Hoort bij een opdracht maar is de opgave niet: tips, sjablonen, rubrics.
_AUXILIARY_RE = re.compile(
    r"(?<![a-z])(?:recommendations?|advice|advies|tips|templates?|rubrics?|guidelines?|feedback|"
    r"examples?|voorbeelden?|aux(?:iliary)?|faq|hints?)(?![a-z])",
    re.IGNORECASE,
)


def clean_filename(name: str) -> str:
    """Canvas geeft `Section+6.2.pdf` en `Koole+%282019%29.pdf`."""
    return unquote(name.replace("+", " "))


def normalize_name(name: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).split())


def corpus_basename(filename: str) -> str:
    """De naam die het bestand in het corpus krijgt; om te zien of het er al staat."""
    return sanitize_filename(clean_filename(filename)).lower()


def _week_for_lecture(course: Course, number: int) -> int | None:
    for key, plan in (course.week_plans or {}).items():
        if number in (plan.get("lectures") or []):
            return int(key)
    return None


def _week_for_section(course: Course, section: str) -> int | None:
    for key, plan in (course.week_plans or {}).items():
        for reading in plan.get("reading") or []:
            if section in (reading.get("sections") or []):
                return int(key)
    return None


def _assignment_entry(course: Course, *, title: str | None, ordinal: int | None) -> dict | None:
    """De opdracht uit course.yml: op naam als het bestand bij een Canvas-
    opdracht hing, anders op volgnummer (`SSO_assignment1` → 'Assignment 1')."""
    entries = course.assignments or []
    if title:
        wanted = normalize_name(title)
        return next((entry for entry in entries if normalize_name(entry.get("name")) == wanted), None)
    if ordinal is not None:
        for entry in entries:
            digits = re.findall(r"\d+", entry.get("name") or "")
            if digits and int(digits[-1]) == ordinal:
                return entry
    return None


def propose_placement(file: CanvasFile, course: Course, *, corpus_root: Path) -> Proposal:
    name = clean_filename(file.filename)
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        allowed = sorted(SUPPORTED_SUFFIXES)
        listed = ", ".join(allowed[:-1]) + f" en {allowed[-1]}"
        return Proposal(None, f"'{suffix or name}' wordt niet geïndexeerd (alleen {listed})", unsupported=True)

    stem = Path(name).stem
    # De uitwerking van een oud tentamen mag wél: een tentamen valt buiten de
    # spoilerfilter, en zonder uitwerking kun je het oude tentamen niet nakijken.
    if (solution := _SOLUTION_RE.search(stem)) is not None and not _EXAM_RE.search(stem):
        return Proposal(
            None,
            f"'{solution.group(0)}' in de naam: lijkt een uitwerking — zet die zelf in solutions/ of "
            "submissions/, want daar kijkt de spoilerfilter naar",
        )

    folder = file.folder or ""
    module = file.module_name or ""
    source = file.source or ""
    # Ook de naam waaronder de docent het bestand linkt: het voorblad van de
    # SSO-herkansing heet als bestand alleen "ANS frontcover and formula sheet".
    shown = clean_filename(file.display_name or "")
    haystack = f"{folder} {module} {name} {shown}"
    module_week = _WEEK_RE.search(module)

    def place(kind: str, week: int | None, reason: str) -> Proposal:
        path = build_corpus_path(corpus_root=corpus_root, course_slug=course.slug, doc_kind=kind, week=week, filename=name)
        return Proposal(Placement(kind, week, path.relative_to(corpus_root.resolve()).as_posix()), reason)

    # Opdracht: gelinkt vanuit een Canvas-opdracht, of zo genoemd. De week komt
    # uit course.yml; zonder regel daar blijft het liggen (Assignment 0, een
    # uitwerking).
    assignment_title = source.split(":", 1)[1] if source.startswith("assignment:") else None
    named = _ASSIGNMENT_RE.search(name)
    if assignment_title is not None or named:
        ordinal = int(named.group(1)) if named and named.group(1) else None
        entry = _assignment_entry(course, title=assignment_title, ordinal=ordinal)
        if entry is None:
            if assignment_title is not None:
                return Proposal(None, f"opdrachtblad bij '{assignment_title}', maar die staat niet in course.yml — week onbekend")
            return Proposal(None, f"'{named.group(0).strip()}' in de naam, maar geen opdracht in course.yml past — week onbekend")
        week = int(entry["week"])
        if (auxiliary := _AUXILIARY_RE.search(stem)) is not None:
            # Een notitie in dezelfde week: vindbaar bij de opdracht, maar geen
            # tweede opgavenblad waar de coach-link naartoe zou wijzen.
            return place(
                "note",
                week,
                f"hoort bij '{entry['name']}' (week {week} volgens course.yml), maar "
                f"'{auxiliary.group(0)}' in de naam: geen opgavenblad",
            )
        if assignment_title is not None:
            return place("assignment", week, f"hoort bij opdracht '{assignment_title}', week {week} volgens course.yml")
        return place("assignment", week, f"'{entry['name']}' in de naam; week {week} volgens course.yml")

    # College: het nummer uit de naam of de map; de week uit de module ("Week
    # 3") of uit `lectures:` in course.yml.
    # Code bij een college (de demo's van SSO deel 2, "lecture_13_crn.py") is een
    # notitie in dezelfde week: als slides telde hij mee als college en werd hij
    # bij het uitdunnen van de weekkaart nooit weggelaten.
    lecture = _LECTURE_RE.search(name) or _LECTURE_FOLDER_RE.search(folder)
    if lecture:
        number = int(lecture.group(1))
        kind = "note" if suffix in (".py", ".ipynb") else "slides"
        code = " (code)" if kind == "note" else ""
        if module_week:
            return place(kind, int(module_week.group(1)), f"college {number}{code} in module '{module}'")
        week = _week_for_lecture(course, number)
        if week is None:
            return Proposal(None, f"college {number}, maar geen week in course.yml noemt college {number} (voeg lectures: toe)")
        return place(kind, week, f"college {number}{code}, week {week} volgens lectures: in course.yml")

    # Oefeningen: een map Exercises, of "Section 6.2" uit het boek. De week
    # volgt het leesplan als de paragraaf daar staat.
    section = _SECTION_RE.search(name)
    if section or re.search(r"exercise|opgave", haystack, re.IGNORECASE):
        label = section.group(1) if section else None
        if module_week:
            week: int | None = int(module_week.group(1))
        else:
            week = _week_for_section(course, label) if label else None
        if label and week is not None:
            return place("exercise", week, f"oefeningen bij paragraaf {label}, week {week} volgens het leesplan")
        if label:
            return place("exercise", None, f"oefeningen bij paragraaf {label}; die staat in geen leesplan, dus zonder week")
        return place("exercise", week, f"in de map '{folder or module}'")

    if (exam := _EXAM_RE.search(haystack)) is not None:
        return place("exam", None, f"tentamen: '{exam.group(0)}' in de naam of de map ('{folder or module}')")
    if re.search(r"\bbook\b|\bboek\b", haystack, re.IGNORECASE):
        return place("book", None, f"boek (map '{folder or module}')")
    if (year := _YEAR_PREFIX_RE.search(name)) is not None:
        return place("paper", None, f"artikel: jaartal {year.group(1)} vooraan in de naam")
    if _ET_AL_RE.search(name):
        return place("paper", None, "artikel: 'et al.' in de naam")
    if _LITERATURE_RE.search(f"{folder} {module}"):
        return place("paper", None, f"leesstof in de map '{folder or module}'")

    return Proposal(None, f"geen regel herkent dit bestand (map '{folder or module or '-'}'); kies soort en week zelf")


def material_state(file: CanvasFile, proposal: Proposal, existing: Document | None) -> str:
    """ignored | downloaded | in_corpus | unsupported | unplaced | new.

    `existing` is het document met dezelfde bestandsnaam in het corpus van dit
    vak. "Opgehaald" alleen als dat hetzelfde document is: wie het daarna
    verwijdert, ziet het bestand weer als nieuw."""
    if file.ignored_at is not None:
        return "ignored"
    if existing is not None:
        return "downloaded" if file.document_id == existing.id else "in_corpus"
    if proposal.unsupported:
        return "unsupported"
    if proposal.placement is None:
        return "unplaced"
    return "new"


_LAB_RE = re.compile(r"\blab\b", re.IGNORECASE)


def propose_page(page: CanvasPage, course: Course, *, corpus_root: Path) -> Proposal:
    """Een pagina is een notitie, of een oefening als het een lab is (dan geeft
    de coach er hints op). Er is altijd een plek: een notitie mag bij het hele
    vak horen. De week komt uit een collegenummer in de titel dat course.yml
    kent, anders uit de module."""
    title = page.title or page.page_url
    kind = "exercise" if _LAB_RE.search(title) else "note"
    module = page.module_name or ""
    lecture = _LECTURE_RE.search(title)
    lecture_week = _week_for_lecture(course, int(lecture.group(1))) if lecture else None
    module_week = _WEEK_RE.search(module)
    if lecture_week is not None:
        week: int | None = lecture_week
        reason = f"over college {lecture.group(1)}, week {week} volgens lectures: in course.yml"
    elif module_week is not None:
        week = int(module_week.group(1))
        reason = f"pagina in module '{module}'"
    else:
        week = None
        reason = f"pagina zonder week (module '{module or '-'}'): hoort bij het hele vak"
    path = build_corpus_path(corpus_root=corpus_root, course_slug=course.slug, doc_kind=kind, week=week, filename=f"{title}.md")
    return Proposal(Placement(kind, week, path.relative_to(corpus_root.resolve()).as_posix()), reason)


def page_state(page: CanvasPage, existing: Document | None) -> str:
    """ignored | downloaded | in_corpus | new — dezelfde regels als bij een bestand."""
    if page.ignored_at is not None:
        return "ignored"
    if existing is not None:
        return "downloaded" if page.document_id == existing.id else "in_corpus"
    return "new"
