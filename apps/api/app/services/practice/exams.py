"""Een (proef)tentamen als oefenkaarten.

Het antwoordmodel staat in `corpus/<vak>/exams/<id>.yml`, met de hand
overgenomen van de scans: de kruisjes in een uitwerking zitten niet in de
tekstlaag van de PDF. Handwerk maakt fouten, dus voordat een transcriptie
kaarten wordt, wordt hij mechanisch nagelopen — de punten moeten optellen, een
open vraag moet een schema hebben dat op zijn puntental uitkomt, en een
rekenvraag moet uitkomen op precies de optie die als goed staat aangemerkt.

Dat laatste is geen theorie: in de conceptuitwerking van het proeftentamen van
FDS stond bij de false negative rate eerst 5/6 aangekruist, en pas daarna 1/6.

Hetzelfde formaat draagt de scenario's (`exams/scenarios.yml`): per patroon uit
"Wat zeker terugkomt" de varianten die je op het tentamen kunt verwachten. Die
zijn niet van een docent overgenomen maar bedacht, dus daar rekent een open
vraag zijn getallen na (`checks`), en een scenario is geen tentamen: hij telt
niet mee als oefententamen, als model of als stijlvoorbeeld.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document, PracticeAttempt, PracticeCard
from app.services.practice.generation import _agrees, numbers_in
from app.services.practice.sandbox import HAND_COMPUTATION_RTOL, evaluate


logger = logging.getLogger(__name__)

LETTERS = "abcdefgh"
SEPARATOR = " › "

# Afrondingsruis in een breuk als 1/6; een echte andere optie ligt veel verder weg.
_EXACT = 1e-9
_NUMERIC_OPTION_RE = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*(?:/\s*\d+(?:\.\d+)?\s*)?$")


class RubricItem(BaseModel):
    criterion: str
    points: float = Field(gt=0)


class AnswerCheck(BaseModel):
    """Eén getal uit het modelantwoord, nagerekend: de gegevens uit de vraag als
    toewijzingen, en één uitdrukking die het getal uitrekent."""

    label: str
    setup: str = ""
    expression: str


class ExamQuestion(BaseModel):
    id: str
    page: int = Field(ge=1)
    type: Literal["mc_single", "mc_multi", "open"]
    points: float = Field(gt=0)
    week: int | None = None
    topic: str = ""
    template: str = ""
    material: str = ""
    figure: str = ""
    question: str
    options: list[str] = Field(default_factory=list)
    answer: list[str] = Field(default_factory=list)
    compute: str | None = None
    model_answer: str = ""
    rubric: list[RubricItem] = Field(default_factory=list)
    max_items: int | None = Field(default=None, ge=1)
    explanation: str = ""
    checks: list[AnswerCheck] = Field(default_factory=list)

    @property
    def is_choice(self) -> bool:
        return self.type != "open"


class ExamSection(BaseModel):
    number: int
    title: str
    # Alleen bij scenario's: het patroon uit voorbereiding.yml (p1, p2, ...).
    pattern: str | None = None
    questions: list[ExamQuestion]


class ExamBlueprint(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str
    course: str
    source: str = ""
    solution: str = ""
    duration_minutes: int | None = None
    total_points: float = Field(gt=0)
    rules: list[str] = Field(default_factory=list)
    sections: list[ExamSection]

    def questions(self) -> list[tuple[ExamSection, ExamQuestion]]:
        return [(section, question) for section in self.sections for question in section.questions]


@dataclass
class ExamImport:
    path: str
    exam_id: str | None = None
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    retired: int = 0
    problems: list[str] = field(default_factory=list)

    def as_line(self) -> str:
        if self.problems:
            return f"{self.path}: niet geïmporteerd — {'; '.join(self.problems)}"
        return (
            f"{self.exam_id}: {self.created} nieuw, {self.updated} bijgewerkt, "
            f"{self.unchanged} ongewijzigd" + (f", {self.retired} vervallen" if self.retired else "")
        )


def as_number(option: str) -> Fraction | None:
    if not _NUMERIC_OPTION_RE.match(option):
        return None
    try:
        return Fraction(option.replace(" ", ""))
    except (ValueError, ZeroDivisionError):
        return None


def check_blueprint(blueprint: ExamBlueprint, *, scenarios: bool = False) -> list[str]:
    """Wat er aan de transcriptie mankeert, zonder iets uit te voeren."""
    problems: list[str] = []
    questions = blueprint.questions()

    if scenarios:
        for section in blueprint.sections:
            if not section.pattern:
                problems.append(f"sectie {section.number}: een scenario hoort bij een patroon ('pattern' ontbreekt)")

    ids = [question.id for _, question in questions]
    dubbel = sorted({qid for qid in ids if ids.count(qid) > 1})
    if dubbel:
        problems.append(f"vraag-id's komen dubbel voor: {', '.join(dubbel)}")

    totaal = sum(question.points for _, question in questions)
    if abs(totaal - blueprint.total_points) > _EXACT:
        problems.append(f"de vragen tellen op tot {totaal:g} punten, niet tot {blueprint.total_points:g}")

    for _, question in questions:
        label = f"vraag {question.id}"
        if question.is_choice:
            if len(question.options) < 2:
                problems.append(f"{label}: minder dan twee opties")
                continue
            if len({option.strip().lower() for option in question.options}) != len(question.options):
                problems.append(f"{label}: twee opties zijn gelijk")
            geldig = LETTERS[: len(question.options)]
            onbekend = [letter for letter in question.answer if letter not in geldig]
            if onbekend:
                problems.append(f"{label}: antwoord {', '.join(onbekend)} is geen optie")
            if question.type == "mc_single" and len(question.answer) != 1:
                problems.append(f"{label}: één goed antwoord verwacht, {len(question.answer)} gegeven")
            if question.type == "mc_multi" and not question.answer:
                problems.append(f"{label}: geen goed antwoord aangemerkt")
            # Een rekenvraag zonder narekening is precies de vraag waar een
            # verkeerd aangekruist antwoord ongemerkt doorheen glipt.
            if all(as_number(option) is not None for option in question.options) and not question.compute:
                problems.append(f"{label}: alle opties zijn getallen, maar 'compute' ontbreekt")
        else:
            if not question.rubric:
                problems.append(f"{label}: open vraag zonder beoordelingsschema")
                continue
            schema = sum(item.points for item in question.rubric)
            if abs(schema - question.points) > _EXACT:
                problems.append(f"{label}: het schema telt op tot {schema:g}, de vraag is {question.points:g} punten")
            if not question.model_answer.strip():
                problems.append(f"{label}: open vraag zonder modelantwoord")
    return problems


def verify_computations(blueprint: ExamBlueprint) -> list[str]:
    """Reken elke `compute` na: hij moet op de goede optie vallen, en op geen andere."""
    problems: list[str] = []
    for _, question in blueprint.questions():
        if not question.is_choice or not question.compute:
            continue
        label = f"vraag {question.id}"
        result = evaluate("", question.compute)
        if result.error or result.number is None:
            problems.append(f"{label}: 'compute' levert geen getal op ({result.error or result.value_repr})")
            continue

        treffers = [
            LETTERS[index]
            for index, option in enumerate(question.options)
            if (value := as_number(option)) is not None
            and abs(float(value) - result.number) <= _EXACT * max(1.0, abs(result.number))
        ]
        if sorted(treffers) != sorted(question.answer):
            uitkomst = f"{result.number:.6g}"
            if not treffers:
                problems.append(f"{label}: 'compute' geeft {uitkomst}, en dat is geen van de opties")
            else:
                problems.append(
                    f"{label}: 'compute' geeft {uitkomst}, dat is optie {', '.join(treffers)} "
                    f"— aangemerkt staat {', '.join(question.answer) or 'niets'}"
                )
    return problems


def verify_checks(questions: list[ExamQuestion]) -> list[str]:
    """Reken elke narekening na: het getal moet in het modelantwoord staan, met
    de marge van een toetskaart, want je rekent met de hand en rondt af."""
    problems: list[str] = []
    for question in questions:
        genoemd = numbers_in(question.model_answer)
        for check in question.checks:
            label = f"vraag {question.id}, narekening '{check.label}'"
            result = evaluate(check.setup, check.expression)
            if result.error or result.number is None or not math.isfinite(result.number):
                problems.append(f"{label} levert geen getal op ({(result.error or result.value_repr)[:80]})")
                continue
            if not any(_agrees(number, result.number, HAND_COMPUTATION_RTOL) for number in genoemd):
                problems.append(f"{label} geeft {round(result.number, 3):g}, en dat staat niet in het modelantwoord")
    return problems


def load_blueprint(path: Path) -> tuple[ExamBlueprint | None, list[str]]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return None, [f"onleesbare YAML: {' '.join(str(exc).split())[:160]}"]
    try:
        blueprint = ExamBlueprint.model_validate(raw)
    except ValidationError as exc:
        fouten = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()[:5]
        ]
        return None, fouten
    scenarios = path.name == SCENARIOS_FILE
    return blueprint, check_blueprint(blueprint, scenarios=scenarios) or verify_computations(blueprint)


def _card_values(
    blueprint: ExamBlueprint,
    section: ExamSection,
    question: ExamQuestion,
    document: Document | None,
    chunk_id: str,
) -> dict:
    spec: dict = {
        "exam": blueprint.id,
        "question_id": question.id,
        "section": f"{section.number} {section.title}",
        "section_number": section.number,
        "template": question.template,
        "topic": question.topic,
        "material": question.material,
        "figure": question.figure.strip(),
    }
    if section.pattern:
        spec["pattern"] = section.pattern
    if question.checks:
        # In de kaart, zodat een veranderde narekening als verandering telt en
        # opnieuw wordt nagerekend.
        spec["checks"] = [check.model_dump() for check in question.checks]
    if question.is_choice:
        spec |= {
            "options": list(question.options),
            "multi": question.type == "mc_multi",
            "answer": [LETTERS.index(letter) for letter in question.answer],
            "compute": question.compute,
        }
        reference = ", ".join(question.answer)
    else:
        spec |= {
            "rubric": [item.model_dump() for item in question.rubric],
            "max_items": question.max_items,
        }
        reference = question.model_answer.strip()

    return {
        "course_slug": blueprint.course,
        "document_id": document.id if document else "",
        "chunk_id": chunk_id,
        "section_path": f"{blueprint.title}{SEPARATOR}{section.number} {section.title}",
        "page_start": question.page,
        "page_end": question.page,
        "kind": "mc" if question.is_choice else "open",
        "setup": "",
        "question": question.question.strip(),
        "reference_answer": reference,
        "explanation": question.explanation.strip(),
        "spec": spec,
        "points": question.points,
        "week": question.week,
    }


def import_exam(db: Session, path: Path) -> ExamImport:
    """Zet één transcriptie om in kaarten; opnieuw importeren werkt ze bij.

    Een kaart wordt herkend aan (vak, tentamen, plek), niet aan zijn tekst: een
    verbeterde typfout mag geen tweede kaart opleveren, en je pogingen horen
    bij de vraag te blijven hangen. Scenario's worden herkend aan hun vraag-id:
    een tentamen ligt vast, maar er komen scenario's bij, en een nieuwe in het
    midden zou alles erna een plek opschuiven.
    """
    report = ExamImport(path=str(path))
    blueprint, problems = load_blueprint(path)
    if blueprint is None or problems:
        # Niets schrijven: een antwoordmodel met één fout kruisje leert je de
        # verkeerde letter aan, en dat merk je pas op het tentamen.
        report.problems = problems
        return report
    report.exam_id = blueprint.id

    document = db.scalar(
        select(Document).where(Document.source_path == f"{blueprint.course}/{blueprint.source}")
    ) if blueprint.source else None

    scenarios = path.name == SCENARIOS_FILE
    def sleutel(position: int, question_id: str | None) -> int | str | None:
        return question_id if scenarios else position

    existing = {
        sleutel(card.position, (card.spec or {}).get("question_id")): card
        for card in db.scalars(
            select(PracticeCard).where(
                PracticeCard.course_slug == blueprint.course,
                PracticeCard.origin == blueprint.id,
            )
        )
    }

    plan: list[tuple[int, dict, PracticeCard | None, dict]] = []
    te_controleren: list[ExamQuestion] = []
    for position, (section, question) in enumerate(blueprint.questions(), start=1):
        chunk_id = ""
        if document is not None:
            chunk_id = db.scalar(
                select(Chunk.id)
                .where(
                    Chunk.document_id == document.id,
                    Chunk.page_start <= question.page,
                    Chunk.page_end >= question.page,
                )
                .order_by(Chunk.chunk_index)
                .limit(1)
            ) or ""

        values = _card_values(blueprint, section, question, document, chunk_id)
        card = existing.pop(sleutel(position, question.id), None)
        veranderd = {} if card is None else {
            key: value for key, value in values.items() if getattr(card, key) != value
        }
        if card is None or veranderd:
            te_controleren.append(question)
        plan.append((position, values, card, veranderd))

    # Alleen wat nieuw of veranderd is: een narekening met scipy kost een
    # seconde, en een ongewijzigd bestand is al eens nagerekend.
    problems = verify_checks(te_controleren)
    if problems:
        report.problems = problems
        return report

    for position, values, card, veranderd in plan:
        if card is None:
            db.add(PracticeCard(origin=blueprint.id, position=position, **values))
            report.created += 1
            continue

        if card.disabled:
            veranderd["disabled"] = False
        if card.position != position:
            # Een scenario dat opschoof doordat er een bijkwam: zelfde vraag,
            # andere plek in de ronde. Niets na te rekenen.
            veranderd["position"] = position
        if veranderd:
            for key, value in veranderd.items():
                setattr(card, key, value)
            report.updated += 1
        else:
            report.unchanged += 1

    # Vragen die uit de transcriptie verdwenen zijn: uitschakelen, niet wissen,
    # zodat pogingen hun verwijzing houden.
    for card in existing.values():
        if not card.disabled:
            card.disabled = True
            report.retired += 1

    db.commit()
    return report


# De opbouw van het echte tentamen (zie `practice_exams.ExamLayout`) en de
# analyse voor de tab Tentamen (`study.exam_prep`) staan naast de transcripties,
# maar zijn er geen: als transcriptie gelezen werden ze bij elke sync als kapot
# gemeld.
LAYOUT_FILE = "opbouw.yml"
PREP_FILE = "voorbereiding.yml"
# De scenario's wel als kaarten, maar niet als transcriptie: anders werd het
# grootste bestand het model voor elk oefententamen, en dienden bedachte vragen
# als stijlvoorbeeld voor de generator.
SCENARIOS_FILE = "scenarios.yml"
NOT_TRANSCRIPTIONS = frozenset({LAYOUT_FILE, PREP_FILE, SCENARIOS_FILE})


def transcription_paths(folder: Path) -> list[Path]:
    """De tentamentranscripties in een map `exams/`, zonder opbouw, analyse en scenario's."""
    if not folder.is_dir():
        return []
    return [path for path in sorted(folder.glob("*.yml")) if path.name not in NOT_TRANSCRIPTIONS]


def import_course_exams(db: Session, course_slug: str, corpus_root: Path) -> list[ExamImport]:
    folder = corpus_root / course_slug / "exams"
    paths = transcription_paths(folder)
    if (folder / SCENARIOS_FILE).is_file():
        paths.append(folder / SCENARIOS_FILE)
    return [import_exam(db, path) for path in paths]


def is_scenario(card: PracticeCard) -> bool:
    """Een oefenvraag bij een patroon, geen vraag van een (oefen)tentamen."""
    return bool((card.spec or {}).get("pattern"))


# --- overzicht voor de oefenpagina ------------------------------------------


@dataclass
class SectionProgress:
    number: int
    title: str
    question_count: int = 0
    points: float = 0.0
    # Vragen met minstens één poging, de punten die die samen waard zijn, en wat
    # je er bij je laatste poging op haalde. Zo zie je per onderdeel waar de
    # punten weglekken, en niet alleen een eindcijfer.
    answered: int = 0
    answered_points: float = 0.0
    last_score: float = 0.0


@dataclass
class ExamProgress:
    origin: str
    title: str
    sections: list[SectionProgress] = field(default_factory=list)

    @property
    def question_count(self) -> int:
        return sum(section.question_count for section in self.sections)

    @property
    def points(self) -> float:
        return sum(section.points for section in self.sections)

    @property
    def answered(self) -> int:
        return sum(section.answered for section in self.sections)

    @property
    def answered_points(self) -> float:
        return sum(section.answered_points for section in self.sections)

    @property
    def last_score(self) -> float:
        return sum(section.last_score for section in self.sections)


def exam_cards(
    db: Session, course_slug: str, origin: str, section_number: int | None = None
) -> list[PracticeCard]:
    cards = db.scalars(
        select(PracticeCard)
        .where(
            PracticeCard.course_slug == course_slug,
            PracticeCard.origin == origin,
            PracticeCard.disabled.is_(False),
        )
        .order_by(PracticeCard.position)
    ).all()
    if section_number is None:
        return list(cards)
    return [card for card in cards if (card.spec or {}).get("section_number") == section_number]


def exam_progress(db: Session, course_slug: str) -> list[ExamProgress]:
    cards = db.scalars(
        select(PracticeCard)
        .where(
            PracticeCard.course_slug == course_slug,
            PracticeCard.origin.is_not(None),
            PracticeCard.disabled.is_(False),
        )
        .order_by(PracticeCard.origin, PracticeCard.position)
    ).all()
    cards = [card for card in cards if not is_scenario(card)]
    if not cards:
        return []

    # De laatste poging per kaart telt: hij zegt wat je nú kunt, niet wat je
    # ooit een keer goed had.
    laatste: dict[str, float] = {}
    for card_id, score in db.execute(
        select(PracticeAttempt.card_id, PracticeAttempt.score)
        .where(PracticeAttempt.card_id.in_([card.id for card in cards]))
        .order_by(PracticeAttempt.created_at)
    ):
        laatste[card_id] = score or 0.0

    exams: dict[str, ExamProgress] = {}
    for card in cards:
        spec = card.spec or {}
        exam = exams.get(card.origin)
        if exam is None:
            titel = (card.section_path or card.origin).split(SEPARATOR)[0]
            exam = exams[card.origin] = ExamProgress(origin=card.origin, title=titel)

        number = spec.get("section_number") or 0
        section = next((item for item in exam.sections if item.number == number), None)
        if section is None:
            section = SectionProgress(number=number, title=(spec.get("section") or "").split(" ", 1)[-1])
            exam.sections.append(section)

        section.question_count += 1
        section.points += card.points or 0.0
        if card.id in laatste:
            section.answered += 1
            section.answered_points += card.points or 0.0
            section.last_score += laatste[card.id]

    for exam in exams.values():
        exam.sections.sort(key=lambda item: item.number)
    return list(exams.values())
