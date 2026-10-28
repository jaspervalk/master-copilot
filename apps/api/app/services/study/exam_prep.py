"""De tab Tentamen: alles voor de voorbereiding op één plek.

Twee soorten inhoud. Het berekende deel komt uit wat er al is: de datum
(`horizon`), de opbouw (`exams/opbouw.yml`), de oefententamens en je pogingen
daarop. Het geanalyseerde deel — patronen die steeds terugkomen, voorspelde
vragen, manieren om punten te halen — staat per vak in
`exams/voorbereiding.yml`. Dat bestand is nu met de hand gevuld uit de oude
tentamens, college 13 en Canvas; een generator kan later hetzelfde formaat
vullen.

Wat mechanisch blijft: elke bewering draagt een bron met een letterlijk
citaat, en die wordt bij elke aanvraag teruggezocht in de geïndexeerde tekst.
Een bron die niet (meer) te vinden is wordt gemarkeerd, niet verborgen: zo zie
je dat een bewering nergens op steunt, ook als het materiaal later verandert.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CanvasAnnouncement, Chunk, Course, Document, PracticeAttempt, PracticeCard
from app.schemas import MAX_TASK_LINKS, TaskLink
from app.services.canvas.client import strip_html
from app.services.practice.exam_generation import squash
from app.services.practice.exams import PREP_FILE, ExamProgress, exam_progress, is_scenario
from app.services.practice.practice_exams import ExamLayout, NoBlueprint, course_blueprint, course_layout
from app.services.study.horizon import Exam, next_exam


# Korter dan dit zegt een gevonden citaat niets: "exam" staat in elk college.
MIN_QUOTE_CHARS = 20


class _Strict(BaseModel):
    # Een tikfout in een sleutel (`sourcse`) zou anders een bewering zonder bron
    # opleveren die er in het bestand mét bron uitziet.
    model_config = ConfigDict(extra="forbid")


class Source(_Strict):
    path: str | None = None
    announcement: str | None = None
    page: int | None = None
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def _one_kind(self) -> "Source":
        if (self.path is None) == (self.announcement is None):
            raise ValueError("een bron noemt óf een document (path) óf een aankondiging (announcement)")
        return self


class Pattern(_Strict):
    id: str
    title: str
    detail: str = ""
    group: int | None = None
    seen: int | None = Field(default=None, ge=0)
    of: int | None = Field(default=None, ge=1)
    sources: list[Source] = Field(default_factory=list)


class Prediction(_Strict):
    id: str
    group: int | None = None
    points: float | None = Field(default=None, gt=0)
    question: str
    answer: str
    why: str = ""
    sources: list[Source] = Field(default_factory=list)


class Tactic(_Strict):
    id: str
    title: str
    detail: str = ""
    sources: list[Source] = Field(default_factory=list)


class Rule(_Strict):
    """Zo herken je de vraag: wat je ziet, wat je dan doet, waar de punten zitten
    en wat de valkuil is. `new` markeert stof die nog nooit op een oud tentamen
    stond (PuLP bij SSO): daar is het huiswerk de bron, niet de ervaring."""

    id: str
    group: int | None = None
    new: bool = False
    see: str
    do: str
    points: str = ""
    trap: str = ""
    sources: list[Source] = Field(default_factory=list)


class PlanStep(_Strict):
    """Wat je nog doet tot het tentamen, in volgorde. Een stap die een
    oefententamen is (`exam`) toont je voortgang en is af als alles gemaakt is;
    de andere vink je zelf af. De knoppen volgen de regel van een agendataak."""

    id: str
    title: str
    day: str = ""
    detail: str = ""
    minutes: int | None = Field(default=None, gt=0)
    exam: str | None = None
    links: list[TaskLink] = Field(default_factory=list, max_length=MAX_TASK_LINKS)
    # De slides die bij de stap horen, als eigen rij: "College 3 · p. 12–23" zegt waar
    # je moet kijken; de knoppen hierboven zijn voor opgaven en uitwerkingen.
    slides: list[TaskLink] = Field(default_factory=list, max_length=MAX_TASK_LINKS)


class ExamFacts(_Strict):
    duration_minutes: int | None = Field(default=None, gt=0)
    aids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PrepFile(_Strict):
    exam: ExamFacts = Field(default_factory=ExamFacts)
    patterns: list[Pattern] = Field(default_factory=list)
    predictions: list[Prediction] = Field(default_factory=list)
    tactics: list[Tactic] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
    plan: list[PlanStep] = Field(default_factory=list)

    def items(self) -> list[Pattern | Prediction | Tactic]:
        return [*self.patterns, *self.predictions, *self.tactics, *self.rules]


def load_prep(path: Path, groups: set[int] | None) -> tuple[PrepFile | None, list[str]]:
    """Het bestand, plus wat er niet aan klopt.

    Alleen een bestand dat niet te lezen is valt weg. De rest wordt gemeld en
    blijft staan: een dubbele id maakt de andere twintig voorspellingen niet
    minder waar.
    """
    try:
        prep = PrepFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except (yaml.YAMLError, ValidationError) as exc:
        return None, [f"{path.name} is niet te lezen: {str(exc).splitlines()[0]}"]

    problems: list[str] = []
    gezien: set[str] = set()
    for step in prep.plan:
        if step.id in gezien:
            problems.append(f"{step.id} staat er twee keer in")
        gezien.add(step.id)
    for item in prep.items():
        if item.id in gezien:
            problems.append(f"{item.id} staat er twee keer in")
        gezien.add(item.id)
        if not item.sources:
            problems.append(f"{item.id} staat er zonder bron")
        group = getattr(item, "group", None)
        if groups is not None and group is not None and group not in groups:
            problems.append(f"{item.id} noemt groep {group}, die niet in de opbouw staat")
    for pattern in prep.patterns:
        if pattern.seen is not None and pattern.of is not None and pattern.seen > pattern.of:
            problems.append(f"{pattern.id}: gezien in {pattern.seen} van {pattern.of} tentamens kan niet")
    return prep, problems


@dataclass(frozen=True)
class SourceCheck:
    source: Source
    found: bool
    label: str
    reason: str | None = None
    href: str | None = None


def _page_label(title: str, page: int | None) -> str:
    return f"{title}, p. {page}" if page is not None else title


def check_sources(db: Session, course_slug: str, sources: list[Source]) -> list[SourceCheck]:
    """Zoek elk citaat terug, met dezelfde `squash` als de citaatcontrole van de
    generator: PDF-tekst breekt woorden af en zet spaties waar ze niet horen."""
    documenten: dict[str, tuple[Document | None, list[tuple[int, int, str]]]] = {}
    aankondigingen: list[CanvasAnnouncement] | None = None
    checks: list[SourceCheck] = []

    for source in sources:
        citaat = squash(source.quote)

        if source.announcement is not None:
            if aankondigingen is None:
                course = db.get(Course, course_slug)
                aankondigingen = [] if course is None or course.canvas_id is None else list(db.scalars(
                    select(CanvasAnnouncement).where(CanvasAnnouncement.canvas_course_id == course.canvas_id)
                ))
            wanted = source.announcement.lower()
            match = next((item for item in aankondigingen if wanted in item.title.lower()), None)
            if match is None:
                checks.append(SourceCheck(source, False, f"Aankondiging: {source.announcement}",
                                          "geen aankondiging met die titel"))
                continue
            label = f"Aankondiging: {match.title}"
            if len(citaat) < MIN_QUOTE_CHARS:
                checks.append(SourceCheck(source, False, label, "citaat te kort om na te lopen", match.html_url))
            elif citaat in squash(f"{match.title} {strip_html(match.body)}"):
                checks.append(SourceCheck(source, True, label, None, match.html_url))
            else:
                checks.append(SourceCheck(source, False, label, "citaat niet gevonden in de aankondiging", match.html_url))
            continue

        if source.path not in documenten:
            document = db.scalar(
                select(Document).where(Document.source_path == source.path, Document.course_slug == course_slug)
            )
            fragmenten = [] if document is None else [
                (start, end, squash(text)) for start, end, text in db.execute(
                    select(Chunk.page_start, Chunk.page_end, Chunk.text).where(Chunk.document_id == document.id)
                )
            ]
            documenten[source.path] = (document, fragmenten)
        document, fragmenten = documenten[source.path]

        if document is None:
            checks.append(SourceCheck(source, False, _page_label(source.path, source.page),
                                      "document staat niet in de index"))
            continue
        label = _page_label(document.title, source.page)
        if len(citaat) < MIN_QUOTE_CHARS:
            checks.append(SourceCheck(source, False, label, "citaat te kort om na te lopen"))
            continue
        overal = any(citaat in tekst for _, _, tekst in fragmenten)
        if source.page is None:
            checks.append(SourceCheck(source, overal, label, None if overal else "citaat niet gevonden in het document"))
            continue
        hier = any(citaat in tekst for start, end, tekst in fragmenten if start <= source.page <= end)
        if hier:
            checks.append(SourceCheck(source, True, label))
        elif overal:
            checks.append(SourceCheck(source, False, label, "citaat staat op een andere pagina"))
        else:
            checks.append(SourceCheck(source, False, label, "citaat niet gevonden in het document"))
    return checks


@dataclass
class GroupStanding:
    number: int
    title: str
    points: float
    mc: int
    open: int
    # Wat een vraag waard is, zodat de pagina het tempo in echte vragen kan
    # uitdrukken: "een open vraag van 4 punten" bestaat bij SSO niet.
    mc_points: float = 1.0
    open_points: list[float] = field(default_factory=list)
    # Vragen met een poging, wat die samen waard zijn, en wat je bij je
    # laatste poging haalde. `share` is None zolang je de groep niet oefende.
    answered: int = 0
    answered_points: float = 0.0
    scored: float = 0.0

    @property
    def share(self) -> float | None:
        return self.scored / self.answered_points if self.answered_points > 0 else None

    @property
    def to_gain(self) -> float:
        """Wat er op het tentamen in deze groep nog te halen valt als je scoort
        zoals bij je laatste pogingen. Niet geoefend: de hele groep."""
        return self.points if self.share is None else self.points * (1 - self.share)


def _title_key(text: str) -> str:
    return squash(text)


def standings(db: Session, course_slug: str, layout: ExamLayout, *, blueprint_id: str | None) -> list[GroupStanding]:
    """Per groep van de opbouw: wat hij waard is en hoe je ervoor staat, met de
    meeste te winnen punten bovenaan.

    Een kaart hoort bij een groep via zijn vraag-id in `examples` (alleen voor
    het proeftentamen, want daar wijzen die ids naar), anders via de titel van
    zijn sectie. Zo tellen het proeftentamen van vorig jaar (vijf secties) en de
    oefententamens in de opbouw van 2026 (zes groepen) allebei mee.
    """
    groups = [
        GroupStanding(
            number=section.number,
            title=section.title,
            points=sum(slot.points for slot in section.slots()),
            mc=section.mc,
            open=len(section.open),
            mc_points=section.mc_points,
            open_points=[float(points) for points in section.open],
        )
        for section in layout.sections
    ]
    by_number = {group.number: group for group in groups}
    by_title = {_title_key(group.title): group for group in groups}
    by_example = {example: by_number[section.number] for section in layout.sections for example in section.examples}

    cards = db.scalars(
        select(PracticeCard).where(
            PracticeCard.course_slug == course_slug,
            PracticeCard.origin.is_not(None),
            PracticeCard.disabled.is_(False),
        )
    ).all()
    laatste: dict[str, float] = {}
    if cards:
        for card_id, score in db.execute(
            select(PracticeAttempt.card_id, PracticeAttempt.score)
            .where(PracticeAttempt.card_id.in_([card.id for card in cards]))
            .order_by(PracticeAttempt.created_at)
        ):
            laatste[card_id] = score or 0.0

    for card in cards:
        # Een scenario is oefening, geen tentamenvraag: drie keer hetzelfde
        # scenario oefenen zou je kans op het tentamen rooskleuriger maken.
        if card.id not in laatste or is_scenario(card):
            continue
        spec = card.spec or {}
        group = None
        if blueprint_id is not None and card.origin == blueprint_id:
            group = by_example.get(spec.get("question_id"))
        if group is None:
            group = by_title.get(_title_key((spec.get("section") or "").split(" ", 1)[-1]))
        if group is None:
            continue
        group.answered += 1
        group.answered_points += card.points or 0.0
        group.scored += laatste[card.id]

    return sorted(groups, key=lambda group: -group.to_gain)


@dataclass
class ScenarioRow:
    """Eén scenario bij een patroon, met wat je bij je laatste poging haalde."""

    card_id: str
    question_id: str
    topic: str
    points: float
    origin: str
    section_number: int
    last_score: float | None = None


def scenarios_by_pattern(db: Session, course_slug: str) -> dict[str, list[ScenarioRow]]:
    """Per patroon (p1, p2, ...) de scenario's uit `exams/scenarios.yml`, in volgorde."""
    cards = [
        card
        for card in db.scalars(
            select(PracticeCard)
            .where(
                PracticeCard.course_slug == course_slug,
                PracticeCard.origin.is_not(None),
                PracticeCard.disabled.is_(False),
            )
            .order_by(PracticeCard.origin, PracticeCard.position)
        )
        if is_scenario(card)
    ]
    laatste: dict[str, float] = {}
    if cards:
        for card_id, score in db.execute(
            select(PracticeAttempt.card_id, PracticeAttempt.score)
            .where(PracticeAttempt.card_id.in_([card.id for card in cards]))
            .order_by(PracticeAttempt.created_at)
        ):
            laatste[card_id] = score or 0.0

    per_patroon: dict[str, list[ScenarioRow]] = {}
    for card in cards:
        spec = card.spec or {}
        per_patroon.setdefault(spec["pattern"], []).append(ScenarioRow(
            card_id=card.id,
            question_id=spec.get("question_id") or "",
            topic=spec.get("topic") or "",
            points=card.points or 0.0,
            origin=card.origin,
            section_number=spec.get("section_number") or 0,
            last_score=laatste.get(card.id),
        ))
    return per_patroon


@dataclass
class ExamPrep:
    course_slug: str
    has_file: bool
    exam: Exam | None = None
    facts: ExamFacts | None = None
    total_points: float | None = None
    minutes_per_point: float | None = None
    groups: list[GroupStanding] = field(default_factory=list)
    exam_sets: list[ExamProgress] = field(default_factory=list)
    patterns: list[tuple[Pattern, list[SourceCheck]]] = field(default_factory=list)
    predictions: list[tuple[Prediction, list[SourceCheck]]] = field(default_factory=list)
    tactics: list[tuple[Tactic, list[SourceCheck]]] = field(default_factory=list)
    rules: list[tuple[Rule, list[SourceCheck]]] = field(default_factory=list)
    plan: list[PlanStep] = field(default_factory=list)
    scenarios: dict[str, list[ScenarioRow]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def build_exam_prep(
    db: Session, course_slug: str, *, corpus_root: Path | None = None, now: datetime | None = None
) -> ExamPrep:
    corpus_root = corpus_root or settings.corpus_dir
    problems: list[str] = []

    layout: ExamLayout | None = None
    blueprint_id: str | None = None
    try:
        blueprint = course_blueprint(course_slug)
        blueprint_id = blueprint.id
        layout = course_layout(course_slug, blueprint)
    except NoBlueprint as exc:
        # Zonder proeftentamen geen opbouw; de pagina toont dan wat er wél is.
        if (corpus_root / course_slug / "exams").is_dir():
            problems.append(str(exc))

    path = corpus_root / course_slug / "exams" / PREP_FILE
    prep: PrepFile | None = None
    if path.is_file():
        groups = {section.number for section in layout.sections} if layout is not None else None
        prep, file_problems = load_prep(path, groups)
        problems += file_problems

    result = ExamPrep(
        course_slug=course_slug,
        has_file=prep is not None,
        exam=next_exam(db, course_slug, now=now),
        facts=prep.exam if prep is not None else None,
        exam_sets=exam_progress(db, course_slug),
        scenarios=scenarios_by_pattern(db, course_slug),
        problems=problems,
    )
    if layout is not None:
        result.total_points = layout.total_points
        result.groups = standings(db, course_slug, layout, blueprint_id=blueprint_id)
        if prep is not None and prep.exam.duration_minutes:
            result.minutes_per_point = prep.exam.duration_minutes / layout.total_points

    if prep is not None:
        # Eén keer nalopen voor alle items samen: per document één query.
        alles = [source for item in prep.items() for source in item.sources]
        checks = iter(check_sources(db, course_slug, alles))
        def _met(items):
            return [(item, [next(checks) for _ in item.sources]) for item in items]
        result.patterns = _met(prep.patterns)
        result.predictions = _met(prep.predictions)
        result.tactics = _met(prep.tactics)
        result.rules = _met(prep.rules)
        result.plan = list(prep.plan)
        bekend = {exam.origin for exam in result.exam_sets}
        for step in prep.plan:
            if step.exam is not None and step.exam not in bekend:
                result.problems.append(f"stap {step.id} wijst naar {step.exam}, maar dat oefententamen is er niet")
    return result
