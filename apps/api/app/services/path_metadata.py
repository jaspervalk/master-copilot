"""Het pad van een bestand binnen `corpus/` is de enige bron van metadata.

Vorm: corpus/<vak>/<map>/[week-NN/]<bestand>. Alles wat daarvan afwijkt wordt
geweigerd — een stille default zou een verkeerd gelabeld document opleveren, en
dat merk je pas als een antwoord ernaast zit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


DOC_KINDS = ("book", "paper", "slides", "assignment", "exercise", "submission", "solution", "note", "exam")
DocKind = Literal["book", "paper", "slides", "assignment", "exercise", "submission", "solution", "note", "exam"]

FOLDER_TO_KIND: dict[str, str] = {
    "books": "book",
    "papers": "paper",
    "slides": "slides",
    # Beoordeeld en ingeleverd: de coach geeft hier alleen hints.
    "assignments": "assignment",
    # Oefenmateriaal dat niet wordt ingeleverd: hints eerst, uitwerking op verzoek.
    "exercises": "exercise",
    "submissions": "submission",
    "solutions": "solution",
    "notes": "note",
    # Een oud of proeftentamen, met of zonder uitwerking. Geen week en buiten de
    # spoilerfilter: het is juist bedoeld om van te leren, en het is de beste
    # aanwijzing die er is voor wat het echte tentamen gaat vragen.
    "exams": "exam",
}
KIND_TO_FOLDER: dict[str, str] = {kind: folder for folder, kind in FOLDER_TO_KIND.items()}

# Markdown voor eigen aantekeningen en voor opgaven die alleen als tekst in
# Canvas staan. Geen .txt: in Canvas zijn dat datasets, geen stof.
SUPPORTED_SUFFIXES = frozenset({".pdf", ".pptx", ".md", ".ipynb", ".py"})

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_WEEK_FOLDER_RE = re.compile(r"^week-(\d{1,2})$")
_WEEK_FILENAME_RE = re.compile(r"(?:^|[^a-z])(?:week[-_ ]?|w)(\d{1,2})(?![0-9])", re.IGNORECASE)


class CorpusPathError(ValueError):
    """Het pad voldoet niet aan corpus/<vak>/<map>/[week-NN/]<bestand>."""


@dataclass(frozen=True)
class CorpusPath:
    course_slug: str
    doc_kind: str
    week: int | None
    relative_path: str
    absolute_path: Path


def sanitize_filename(filename: str) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix.lower()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return f"{cleaned or 'document'}{suffix or '.pdf'}"


def _week_from_filename(filename: str) -> int | None:
    match = _WEEK_FILENAME_RE.search(filename)
    return int(match.group(1)) if match else None


def parse_corpus_path(path: Path, corpus_root: Path) -> CorpusPath:
    absolute = path.resolve()
    root = corpus_root.resolve()
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        raise CorpusPathError(f"{path} ligt niet binnen {corpus_root}") from exc

    parts = relative.parts
    if len(parts) < 3:
        raise CorpusPathError(
            f"'{relative.as_posix()}' mist een map: verwacht <vak>/<map>/[week-NN/]<bestand>"
        )
    if len(parts) > 4:
        raise CorpusPathError(f"'{relative.as_posix()}' is te diep genest")

    course_slug, folder, *rest = parts
    if not _SLUG_RE.match(course_slug):
        raise CorpusPathError(
            f"Vaknaam '{course_slug}' moet kleine letters, cijfers en koppeltekens zijn"
        )

    doc_kind = FOLDER_TO_KIND.get(folder)
    if doc_kind is None:
        raise CorpusPathError(
            f"Onbekende map '{folder}'; toegestaan: {', '.join(sorted(FOLDER_TO_KIND))}"
        )

    if len(rest) == 2:
        week_folder, filename = rest
        match = _WEEK_FOLDER_RE.match(week_folder)
        if match is None:
            raise CorpusPathError(f"'{week_folder}' moet de vorm week-NN hebben")
        week = int(match.group(1))
    else:
        (filename,) = rest
        week = _week_from_filename(filename)

    if Path(filename).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise CorpusPathError(
            f"'{filename}' heeft een niet-ondersteunde extensie; "
            f"toegestaan: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )

    return CorpusPath(
        course_slug=course_slug,
        doc_kind=doc_kind,
        week=week,
        relative_path=relative.as_posix(),
        absolute_path=absolute,
    )


def build_corpus_path(
    *,
    corpus_root: Path,
    course_slug: str,
    doc_kind: str,
    week: int | None,
    filename: str,
) -> Path:
    if not _SLUG_RE.match(course_slug):
        raise CorpusPathError(f"Vaknaam '{course_slug}' is ongeldig")
    folder = KIND_TO_FOLDER.get(doc_kind)
    if folder is None:
        raise CorpusPathError(f"Onbekend documentsoort '{doc_kind}'")

    safe_name = sanitize_filename(filename)
    if Path(safe_name).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise CorpusPathError(f"'{filename}' heeft een niet-ondersteunde extensie")

    destination = corpus_root.resolve() / course_slug / folder
    if week is not None:
        destination = destination / f"week-{week:02d}"
    resolved = (destination / safe_name).resolve()

    # Padtraversal-verdediging: het resultaat moet binnen het corpus vallen.
    if not resolved.is_relative_to(corpus_root.resolve()):
        raise CorpusPathError("Doelpad valt buiten het corpus")
    return resolved
