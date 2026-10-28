"""Oefententamens in de opbouw van het proeftentamen.

Een proeftentamen is 34 vragen, en die ken je na twee rondes uit je hoofd. Een
oefententamen neemt de opbouw over — vijf secties, dezelfde verdeling over
meerkeuze en open vragen, dezelfde puntenaantallen — en vult elke sectie met
nieuwe vragen uit de stof van de weken die erbij horen.

Stof per sectie komt uit BM25 op de onderwerpen van die sectie, binnen de
weken van het leesplan. Een fragment telt alleen als het de onderscheidende
woorden van het onderwerp ook echt bevat; BM25 geeft altijd íets terug.

Dekt de stof minder dan de helft van de punten die een sectie in het
proeftentamen waard was, dan blijft die sectie leeg. De eerste versie
herschreef in dat geval de tekst van het proeftentamen zelf, en leverde een
kaart op die het nagelopen antwoord bij 5d tegensprak: een vraag die de stof
niet kent, gaat de stof invullen.

Nieuw betekent: niet dezelfde vraag in andere woorden, en ook niet een andere
vraag met hetzelfde antwoord. Die ronde leverde anders "very low k in k-NN" en
"give 3 operations pandas can do" op — 3f en 1f met een andere aanloop.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Chunk, Course, Document, PracticeCard
from app.schemas import QueryFilters
from app.services.hybrid_index import get_hybrid_index, refresh_hybrid_index
from app.services.practice.exam_generation import (
    DUPLICATE,
    ExamBatch,
    ExamDraft,
    accept_exam_draft,
    build_card,
    exam_instructions,
    material_block,
    repair_instructions,
    source_chunk,
)
from app.services.practice.exam_style import CHOICE_POINTS, FDS_STYLE, OPEN_POINTS, Scoring, Style
from app.services.practice.exams import (
    LAYOUT_FILE,
    LETTERS,
    SEPARATOR,
    ExamBlueprint,
    ExamQuestion,
    ExamSection,
    as_number,
    load_blueprint,
    transcription_paths,
)
from app.services.weeks import week_scope

try:  # pragma: no cover — de app moet importeerbaar blijven zonder de SDK
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


ORIGIN_PREFIX = "oefententamen-"
TITLE_PREFIX = "Oefententamen"

# Genoeg voor een sectie van 32 punten met een vraag van 10, zonder dat de
# prompt de helft van het boek meekrijgt.
MAX_SECTION_CHARS = 45_000
# Voor een zware open vraag over één onderwerp.
MAX_FOCUS_CHARS = 30_000
HITS_PER_TOPIC = 6
SLIDE_HITS_PER_TOPIC = 3
MIN_SECTION_CHUNKS = 3

# Wat als stof telt. Een ander tentamen, een uitwerking of je eigen inzending
# niet: dan schrijft het model die over in plaats van nieuwe vragen te maken.
MATERIAL_KINDS = ["book", "paper", "slides", "note", "exercise", "assignment"]

# Dekt de stof minder dan dit deel van de punten van een sectie, dan blijft de
# sectie leeg in plaats van dat het model hem invult.
MIN_COVERED_SHARE = 0.5

# Wanneer een vraag een kopie is. Niet omdat de zinsbouw lijkt — "(Mark all
# correct answers)" maakte van een vraag over Naive Bayes een kopie van een
# vraag over K-means — maar omdat hij (bijna) woordelijk gelijk is, hetzelfde
# vraagt over hetzelfde onderwerp, of hetzelfde antwoord heeft.
#
# Woordelijk: de insluiting vangt een vraag waar alleen de aanloop van af is
# ("Provide 3 operations…" zonder "Pandas is a useful framework, …"). Bij een
# open vraag ligt de lat hoger, want "very high k" en "very low k" verschillen
# één woord en hebben een ander antwoord; dat vangt de antwoordvergelijking.
VERBATIM_LIMIT_MC = 0.8
VERBATIM_LIMIT_OPEN = 0.9
# Drie, niet zes: "Explain what distinguishes bagging from random forests" heeft
# vier inhoudswoorden, en die staan alle vier in 3i van het proeftentamen.
VERBATIM_MIN_WORDS = 3
# Een meerkeuzeantwoord van hooguit zoveel woorden is een begrip ("sequential",
# "broadcasting") en geen zin.
CONCEPT_MAX_WORDS = 3
# Zelfde vorm en hetzelfde onderwerp: dan is het dezelfde meerkeuzevraag.
OBJECT_OVERLAP = 0.8
# Wanneer twee open vragen hetzelfde antwoord hebben. Het schema zegt het
# scherpst: wie punten krijgt voor dezelfde dingen, beantwoordt dezelfde vraag —
# "vectorization in plaats van een Python-lus" stond in twee oefententamens met
# een ander scenario en hetzelfde schema.
ANSWER_SIMILARITY_LIMIT = 0.5
ANSWER_CONTAINMENT_LIMIT = 0.7
ANSWER_CONTAINMENT_MIN_WORDS = 8
# Het schema van een open vraag: wie punten krijgt voor dezelfde dingen,
# beantwoordt dezelfde vraag. Lager dan bij het modelantwoord, want een schema
# is korter en zijn woorden zijn preciezer.
RUBRIC_CONTAINMENT_LIMIT = 0.6
# Zelfde vorm en onderwerp telt bij een open vraag pas als ook het schema
# overlapt; "very high k" en "very low k" hebben dezelfde vorm en een ander schema.
RUBRIC_OVERLAP_FOR_OBJECT = 0.3
# Een kort antwoord dat in de vraag zelf staat, is weggegeven: "Gradient descent
# usually takes many steps. Name one numerical optimization method." → "Gradient descent."
GIVEAWAY_MAX_WORDS = 4
# Twee meerkeuzevragen met een goed antwoord dat in andere woorden hetzelfde zegt.
CORRECT_SIMILARITY_LIMIT = 0.5
CORRECT_MIN_WORDS = 4
# Zoveel aanvulrondes voor lege meerkeuze- en lichte open plekken.
FILL_ROUNDS = 2

# Een zware open vraag die in de gewone rondes niet lukt, krijgt zoveel
# pogingen met de stof van één onderwerp.
HEAVY_POINTS = 6
HEAVY_ATTEMPTS = 2

# Woorden die in bijna elk onderwerp en elke tekst staan. "COMPAS case study"
# telde als gedekt door elk hoofdstuk met "case" en "study" erin.
_GENERIC = frozenset(
    {
        "data", "learning", "method", "model", "analysis", "science", "study", "case", "metric", "type",
        "technique", "problem", "application", "evaluating", "evaluation", "using", "based", "basic",
        "introduction", "practice", "versus", "general", "approach", "best", "large", "small",
    }
)

# De steigerwoorden van een vraagvorm: wat overblijft als je die weghaalt, is
# waar de vraag óver gaat.
_SCAFFOLD = frozenset(
    {
        "mark", "all", "correct", "answer", "select", "possible", "true", "false", "define", "definition",
        "typical", "example", "use", "used", "limitation", "requirement", "assumption", "advantage",
        "disadvantage", "benefit", "drawback", "statement", "describe", "characterise", "characterize",
        "identify", "provide", "justify", "list", "assume", "task", "principle", "solved", "solve",
        "category", "kind", "keyword", "called", "term", "well-known", "known", "main", "key", "common",
        # De werkwoorden van een vergelijkingsvraag: "differ" is "distinguish".
        "differ", "difference", "distinguish", "distinguishes", "compare", "compared", "contrast", "valid",
    }
)

_WORD_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_STOPWORDS = frozenset(
    {
        "and", "the", "with", "from", "versus", "into", "for", "that", "this", "are", "what", "which",
        "why", "how", "does", "can", "you", "your", "please", "following", "between", "about",
        "their", "there", "when", "where", "would", "should", "could", "have", "has", "been", "its",
        "one", "two", "give", "name", "explain", "briefly", "consider", "above", "below", "is", "an",
        "then", "they", "them", "these", "those", "also",
    }
)


class NoBlueprint(ValueError):
    """Er is geen proeftentamen om de opbouw van over te nemen."""


@dataclass(frozen=True)
class Slot:
    kind: str
    points: float

    def label(self) -> str:
        if self.kind == "mc":
            return f"meerkeuzevraag van {self.points:g} punt"
        return f"open vraag van {self.points:g} punten"


class LayoutSection(BaseModel):
    number: int
    title: str
    mc: int = Field(ge=0)
    mc_points: float = Field(default=1.0, gt=0)
    # Punten per open vraag, in volgorde.
    open: list[float] = Field(default_factory=list)
    # Ids van vragen uit het proeftentamen die als voorbeeld dienen voor vorm en onderwerp.
    examples: list[str] = Field(default_factory=list)
    # Onderwerpen uit de studiewijzer die bij deze groep horen maar geen woord
    # delen met de titel: link prediction bij "Network Science", regressie bij
    # "Supervised Learning". Zonder dit vallen ze tussen twee groepen in.
    topics: list[str] = Field(default_factory=list)
    # Weken waar de stof ook vandaan mag komen. De voorbeelden van SSO-vraag 1
    # gaan allemaal over week 1, maar de rangtoetsen van week 2 horen erbij.
    weeks: list[int] = Field(default_factory=list)
    # De vormen van de open deelvragen, in volgorde. Gezet: de groep is één
    # situatie met deelvragen die erop voortbouwen, zoals een SSO-vraag. Met een
    # onderwerp per plek kwamen er losse vragen uit, zonder één rekenvraag.
    forms: list[str] = Field(default_factory=list)

    def slots(self) -> list[Slot]:
        return [Slot("mc", self.mc_points)] * self.mc + [Slot("open", float(points)) for points in self.open]


class ExamLayout(BaseModel):
    """De opbouw van het echte tentamen, als die afwijkt van het proeftentamen.

    Het proeftentamen van FDS is van vorig jaar: vijf secties, meerkeuze voor 1,5
    punt, open vragen tot 10. College 13 gaf die van 2026: zes groepen (netwerken
    los van unsupervised), 24 meerkeuzevragen van 1 punt en 21 open vragen van 2
    tot 6. Oefententamens in de oude opbouw oefenen dus een ander tentamen. De
    vragen van het proeftentamen blijven het voorbeeld voor de vorm (`examples`).
    """

    title: str
    source: str = ""
    total_points: float = Field(gt=0)
    sections: list[LayoutSection]
    # De stijl van het vak, als die niet die van FDS is: de inleiding van de
    # instructie, de vraagvormen, en welke vormen rekenvragen zijn waarvan elk
    # getal wordt nagerekend. Het SSO-tentamen is rekenwerk in eigen vormen.
    intro: str = ""
    templates: dict[str, str] = Field(default_factory=dict)
    numeric_templates: list[str] = Field(default_factory=list)
    # Vorm → wat een narekening moet gebruiken, zoals `optimize.` bij grafisch LP.
    solver_templates: dict[str, str] = Field(default_factory=dict)

    def style(self) -> Style:
        return Style(
            intro=self.intro,
            templates=dict(self.templates) or None,
            numeric=frozenset(self.numeric_templates),
            solvers=dict(self.solver_templates) or None,
        )


@dataclass
class SectionPlan:
    number: int
    title: str
    weeks: list[int]
    # De week of weken waar het zwaartepunt van de punten ligt; die bepalen de
    # week op de kaart.
    main_weeks: list[int]
    slots: list[Slot]
    topics: list[str]
    original: list[ExamQuestion]
    # Punten per onderwerp in het proeftentamen; de onderwerpen uit de
    # studiewijzer staan hier niet in.
    topic_points: dict[str, float] = field(default_factory=dict)
    # De onderscheidende woorden van deze sectie: titel, onderwerpen van het
    # proeftentamen, en de onderwerpen uit de studiewijzer die erbij horen.
    theme_words: set[str] = field(default_factory=set)
    # Gezet: één situatie met deelvragen in deze vormen en volgorde.
    forms: list[str] = field(default_factory=list)


@dataclass
class SectionMaterial:
    chunks: list[Chunk]
    per_topic: dict[str, list[Chunk]]
    uncovered: list[str]
    # Welk deel van de punten van deze sectie in het proeftentamen stof heeft.
    covered_share: float


@dataclass
class SectionResult:
    origin: str
    title: str
    section_number: int
    section_title: str
    created: list[PracticeCard] = field(default_factory=list)
    planned_points: float = 0.0
    missing: list[Slot] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    uncovered_topics: list[str] = field(default_factory=list)
    source_note: str = ""

    @property
    def points(self) -> float:
        return sum(card.points or 0.0 for card in self.created)

    def as_lines(self) -> list[str]:
        lines = [
            f"sectie {self.section_number} ({self.section_title}): {len(self.created)} vragen, "
            f"{self.points:g} van {self.planned_points:g} punten"
        ]
        if self.source_note:
            lines.append(f"  let op: {self.source_note}")
        if self.missing:
            teller = Counter(slot.label() for slot in self.missing)
            lines.append("  ontbreekt: " + ", ".join(f"{n}× {label}" for label, n in teller.items()))
        if self.uncovered_topics:
            lines.append("  geen stof gevonden voor: " + ", ".join(self.uncovered_topics))
        for question, reason in self.rejected:
            lines.append(f"  afgekeurd: {question[:60]} — {reason}")
        return lines


# --- woorden -------------------------------------------------------------------


def _words(text: str) -> list[str]:
    woorden = []
    for word in _WORD_RE.findall(text.lower()):
        if len(word) < 2 or word in _STOPWORDS:
            continue
        # Meervoud eraf, zodat "colormaps" ook "colormap" vindt — maar niet bij
        # -ss, -us, -is of -as: "COMPAS" werd "compa" en vond zo elk "compare",
        # en "bias" werd "bia". "probabilities" en "classes" krijgen hun eigen
        # regel; anders werden het "probabilitie" en "classe".
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith(("sses", "ches", "shes", "xes")):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is", "as")):
            word = word[:-1]
        woorden.append(word)
    return woorden


def _canon(word: str) -> str:
    """Eén spelling: zonder koppelteken, Amerikaans."""
    word = word.replace("-", "").replace("isation", "ization")
    return word[:-3] + "or" if word.endswith("our") else word


def _distinctive(text: str) -> set[str]:
    return {_canon(word) for word in _words(text) if word not in _GENERIC and len(word) >= 3}


def _variants(word: str) -> set[str]:
    """Britse en Amerikaanse spelling, en met of zonder koppelteken: "k-NN" staat
    in het boek als "KNN", "neighbours" als "neighbors"."""
    return {
        word,
        word.replace("-", ""),
        word.replace("our", "or"),
        word.replace("isation", "ization"),
        word.replace("ise", "ize"),
    }


def covers(text: str, topic: str) -> bool:
    """Bevat dit fragment het onderwerp, of alleen een toevallig gedeeld woord?

    Alleen de onderscheidende woorden tellen. Bij één of twee moeten ze er
    allemaal staan, bij meer twee derde.
    """
    words = list(dict.fromkeys(word for word in _words(topic) if len(word) >= 3 or "-" in word))
    distinctive = [word for word in words if word not in _GENERIC] or words
    if not distinctive:
        return False
    lowered = text.lower()
    nodig = len(distinctive) if len(distinctive) <= 2 else math.ceil(len(distinctive) * 2 / 3)
    gevonden = sum(
        1 for word in distinctive
        if any(re.search(rf"\b{re.escape(variant)}", lowered) for variant in _variants(word))
    )
    return gevonden >= nodig


# --- de opbouw -----------------------------------------------------------------


def _split_topics(raw: list[str]) -> list[str]:
    """"logistic regression, naive bayes, k-NN" zijn drie onderwerpen."""
    topics: list[str] = []
    for item in raw:
        for part in item.split(","):
            part = part.strip()
            if part and part.lower() not in {topic.lower() for topic in topics}:
                topics.append(part)
    return topics


def plan_sections(blueprint: ExamBlueprint, week_plans: dict, layout: ExamLayout | None = None) -> list[SectionPlan]:
    """De opbouw per sectie, en welke onderwerpen uit de studiewijzer erbij horen.

    Een onderwerp uit de studiewijzer hoort bij een sectie als het een woord deelt
    met de titel of de onderwerpen van die sectie, of als zijn week alleen bij
    die sectie hoort en geen andere sectie er aanspraak op maakt. Week 2 van
    FDS is visualisatie én regressie; zonder die regel kreeg de
    visualisatiesectie een vraag over regularisatie.

    Met een opbouw (`layout`) komen de secties en hun plekken daaruit, en zijn
    de vragen van het proeftentamen die hij als voorbeeld noemt de bron voor
    weken en onderwerpen.
    """
    if layout is not None:
        per_id = {question.id: question for _, question in blueprint.questions()}
        bronnen = [
            ExamSection(number=section.number, title=section.title, questions=[per_id[example] for example in section.examples])
            for section in layout.sections
        ]
        plekken = {section.number: section.slots() for section in layout.sections}
        genoemd = {section.number: list(section.topics) for section in layout.sections}
        extra_weken = {section.number: list(section.weeks) for section in layout.sections}
        vormen = {section.number: list(section.forms) for section in layout.sections}
    else:
        bronnen = list(blueprint.sections)
        plekken = {}
        genoemd = {}
        extra_weken = {}
        vormen = {}

    basis = []
    for section in bronnen:
        per_week: Counter = Counter()
        for question in section.questions:
            if question.week:
                per_week[question.week] += question.points
        zwaarst = max(per_week.values(), default=0)
        main_weeks = sorted(week for week, points in per_week.items() if points * 2 >= zwaarst)
        eigen = _split_topics([question.topic for question in section.questions if question.topic])
        woorden = _distinctive(section.title).union(*(_distinctive(topic) for topic in eigen))
        weken = sorted(set(per_week) | set(extra_weken.get(section.number, [])))
        basis.append((section, weken, main_weeks, eigen, woorden))

    weken_per_sectie = Counter(week for _, weeks, _, _, _ in basis for week in weeks)

    plans: list[SectionPlan] = []
    for section, weeks, main_weeks, eigen, woorden in basis:
        extra: list[str] = []
        for week in weeks:
            for topic in _split_topics(((week_plans or {}).get(str(week)) or {}).get("topics") or []):
                kenmerk = _distinctive(topic)
                if kenmerk & woorden:
                    extra.append(topic)
                    continue
                elders = any(kenmerk & andere for other, _, _, _, andere in basis if other.number != section.number)
                if weken_per_sectie[week] == 1 and not elders:
                    extra.append(topic)

        extra += [topic for topic in genoemd.get(section.number, []) if topic not in extra]

        topic_points: dict[str, float] = {}
        for question in section.questions:
            for topic in _split_topics([question.topic] if question.topic else []):
                topic_points[topic] = topic_points.get(topic, 0.0) + question.points

        plans.append(
            SectionPlan(
                number=section.number,
                title=section.title,
                weeks=weeks,
                main_weeks=main_weeks,
                slots=plekken.get(section.number)
                or [Slot("open" if question.type == "open" else "mc", question.points) for question in section.questions],
                topics=_split_topics(eigen + extra),
                original=list(section.questions),
                topic_points=topic_points,
                theme_words=woorden.union(*(_distinctive(topic) for topic in extra)),
                forms=vormen.get(section.number, []),
            )
        )
    return plans


def course_blueprint(course_slug: str) -> ExamBlueprint:
    """De transcriptie met de meeste punten: het volledigste tentamen. De eerste
    op naam was "college-13", zes losse voorbeeldvragen, en die werden dan het
    model voor elk oefententamen."""
    kandidaten: list[ExamBlueprint] = []
    for path in transcription_paths(settings.corpus_dir / course_slug / "exams"):
        blueprint, problems = load_blueprint(path)
        if blueprint is not None and not problems:
            kandidaten.append(blueprint)
    if kandidaten:
        return max(kandidaten, key=lambda blueprint: blueprint.total_points)
    raise NoBlueprint(f"{course_slug} heeft geen nagelopen proeftentamen in exams/ om de opbouw van over te nemen")


def load_layout(path: Path, blueprint: ExamBlueprint) -> tuple[ExamLayout | None, list[str]]:
    """De opbouw, of de problemen ermee. Mechanisch nagelopen, net als een
    transcriptie: de punten tellen op tot het totaal, en elk voorbeeld bestaat."""
    try:
        layout = ExamLayout.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (yaml.YAMLError, ValidationError) as exc:
        return None, [f"{path.name} is geen geldige opbouw: {str(exc).splitlines()[0]}"]
    problems: list[str] = []
    onbekend = [name for name in layout.numeric_templates if name not in layout.style().forms()]
    if onbekend:
        problems.append(f"rekenvormen zonder beschrijving: {', '.join(onbekend)}")
    totaal = sum(slot.points for section in layout.sections for slot in section.slots())
    if abs(totaal - layout.total_points) > 1e-9:
        problems.append(f"de punten tellen op tot {totaal:g}, niet tot {layout.total_points:g}")
    nummers = [section.number for section in layout.sections]
    if len(set(nummers)) != len(nummers):
        problems.append("twee groepen hebben hetzelfde nummer")
    bekend = {question.id for _, question in blueprint.questions()}
    for section in layout.sections:
        for example in section.examples:
            if example not in bekend:
                problems.append(f"groep {section.number}: voorbeeld {example} staat niet in {blueprint.id}")
        if any(points <= 0 for points in section.open):
            problems.append(f"groep {section.number}: een open vraag heeft positieve punten nodig")
        if section.forms:
            if len(section.forms) != len(section.open):
                problems.append(f"groep {section.number}: {len(section.forms)} vormen voor {len(section.open)} open deelvragen")
            onbekend = [form for form in section.forms if form not in layout.style().forms()]
            if onbekend:
                problems.append(f"groep {section.number}: onbekende vormen {', '.join(onbekend)}")
    return (None, problems) if problems else (layout, [])


def course_layout(course_slug: str, blueprint: ExamBlueprint) -> ExamLayout | None:
    """De opbouw uit `exams/opbouw.yml`, als die er is. Een opbouw die niet klopt
    valt niet stil terug op het proeftentamen: dan zou je een ander tentamen
    oefenen zonder het te weten."""
    path = settings.corpus_dir / course_slug / "exams" / LAYOUT_FILE
    if not path.is_file():
        return None
    layout, problems = load_layout(path, blueprint)
    if layout is None:
        raise NoBlueprint(f"{LAYOUT_FILE} van {course_slug} klopt niet: " + "; ".join(problems))
    return layout


def course_style(course_slug: str) -> Style:
    """De stijl uit de opbouw van het vak, anders die van FDS."""
    layout = course_layout(course_slug, course_blueprint(course_slug))
    return layout.style() if layout is not None else FDS_STYLE


def exam_plans(db: Session, course_slug: str) -> list[SectionPlan]:
    """De secties van een nieuw oefententamen: de opbouw van het echte tentamen
    als die er is, anders die van het proeftentamen."""
    blueprint = course_blueprint(course_slug)
    course = db.get(Course, course_slug)
    return plan_sections(blueprint, course.week_plans if course else {}, layout=course_layout(course_slug, blueprint))


def plan_scoring(plan: SectionPlan) -> Scoring:
    """De puntregels van deze sectie volgen zijn plekken: dan keurt de controle
    precies goed wat er gevraagd wordt."""
    keuze = [slot.points for slot in plan.slots if slot.kind == "mc"]
    open_ = tuple(sorted({slot.points for slot in plan.slots if slot.kind == "open"}))
    return Scoring(choice_points=keuze[0] if keuze else CHOICE_POINTS, open_points=open_ or OPEN_POINTS)


# --- de stof per sectie --------------------------------------------------------


def section_material(db: Session, course_slug: str, plan: SectionPlan) -> SectionMaterial:
    index = get_hybrid_index()
    if not index.ready:
        refresh_hybrid_index(db)

    spans = {week: week_scope(db, course_slug, week).spans for week in plan.weeks}
    ranked: dict[str, list[str]] = {}
    for topic in plan.topics:
        # Over de weken heen op score, niet week na week: anders wint de eerste
        # week elke eerste plek, en sectie 3 kreeg zo wel PDSH hoofdstuk 5 maar
        # geen ISLR over bagging.
        scores: dict[str, float] = {}
        for week in plan.weeks:
            # Ook apart in de slides: een boekhoofdstuk van zestig pagina's wint
            # anders elke plek in de top, en het college komt er niet in.
            for kinds, limit in ((MATERIAL_KINDS, HITS_PER_TOPIC), (["slides"], SLIDE_HITS_PER_TOPIC)):
                filters = QueryFilters(course_slug=course_slug, week=week, doc_kinds=kinds)
                for chunk_id, score in index.search(topic, limit=limit, filters=filters, week_spans=spans[week]):
                    scores[chunk_id] = max(score, scores.get(chunk_id, score))
        ranked[topic] = [chunk_id for chunk_id, _ in sorted(scores.items(), key=lambda item: -item[1])]

    def load(ids: set[str]) -> dict[str, Chunk]:
        return {chunk.id: chunk for chunk in db.scalars(select(Chunk).where(Chunk.id.in_(ids)))} if ids else {}

    by_id = load({chunk_id for ids in ranked.values() for chunk_id in ids})
    per_topic = {
        topic: [by_id[chunk_id] for chunk_id in ids if chunk_id in by_id and covers(by_id[chunk_id].text, topic)]
        for topic, ids in ranked.items()
    }
    # Het tentamen vraagt naar "what we discussed in the lectures". Binnen een
    # onderwerp gaan de slides dus vóór het boek; anders werd de
    # visualisatiesectie matplotlib-trivia, want PDSH hoofdstuk 4 was elf van
    # de veertien fragmenten.
    soort = dict(db.execute(
        select(Document.id, Document.doc_kind).where(Document.id.in_({chunk.document_id for chunk in by_id.values()}))
    ).all()) if by_id else {}
    for topic, chunks in per_topic.items():
        chunks.sort(key=lambda chunk: soort.get(chunk.document_id) != "slides")

    # Staat een onderwerp niet in de stof van die weken, kijk dan in het hele
    # vak: gradient descent staat in ISLR hoofdstuk 10, dat aan geen week hangt.
    # Geteld wordt wat het onderwerp echt bevat.
    for topic, chunks in per_topic.items():
        if len(chunks) >= 2:
            continue
        filters = QueryFilters(course_slug=course_slug, doc_kinds=MATERIAL_KINDS)
        extra = [chunk_id for chunk_id, _ in index.search(topic, limit=HITS_PER_TOPIC, filters=filters)]
        by_id |= load({chunk_id for chunk_id in extra if chunk_id not in by_id})
        for chunk_id in extra:
            chunk = by_id.get(chunk_id)
            if chunk is not None and chunk not in chunks and covers(chunk.text, topic):
                chunks.append(chunk)

    # Om de beurt een fragment per onderwerp, zodat elk onderwerp aan bod komt
    # voordat het budget op is. De onderwerpen van het proeftentamen beginnen een
    # ronde eerder dan die uit de studiewijzer: die zijn zeker binnen het thema.
    gekozen: list[Chunk] = []
    gezien: set[str] = set()
    budget = MAX_SECTION_CHARS
    diepte = max((len(chunks) for chunks in per_topic.values()), default=0) + 1
    for ronde in range(diepte):
        for topic, chunks in per_topic.items():
            rang = ronde if topic in plan.topic_points else ronde - 1
            if rang < 0 or rang >= len(chunks) or chunks[rang].id in gezien:
                continue
            chunk = chunks[rang]
            if len(chunk.text) > budget:
                continue
            gekozen.append(chunk)
            gezien.add(chunk.id)
            budget -= len(chunk.text)

    totaal = sum(plan.topic_points.values())
    gedekt = sum(points for topic, points in plan.topic_points.items() if per_topic.get(topic))
    return SectionMaterial(
        chunks=gekozen,
        per_topic=per_topic,
        uncovered=[topic for topic, chunks in per_topic.items() if not chunks],
        covered_share=gedekt / totaal if totaal else (1.0 if gekozen else 0.0),
    )


# --- nieuwe vragen, geen herformuleringen ---------------------------------------


def _short(text: str) -> str:
    return " ".join(text.split())[:70]


def _similarity_words(text: str) -> set[str]:
    # Zonder steigerwoorden: "limitations" en "(Mark all correct answers)"
    # maken twee vragen niet tot dezelfde vraag.
    return {word for word in _words(text) if len(word) >= 3 and word not in _SCAFFOLD}


def _object_words(text: str) -> set[str]:
    return {_canon(word) for word in _words(text) if len(word) >= 3 and word not in _GENERIC and word not in _SCAFFOLD}


# Onder dit aantal inhoudswoorden zegt woordelijke gelijkheid niets: zonder
# steigerwoorden blijft van "limitation of PCA" en "advantage of PCA" alleen
# {pca} over. Dan beslissen de vorm en het antwoord.
VERBATIM_MIN_JACCARD_WORDS = 3


def _overlaps(left: set[str], right: set[str], jaccard: float, containment: float, min_words: int) -> bool:
    if not left or not right:
        return False
    gedeeld = len(left & right)
    kleinste = min(len(left), len(right))
    if kleinste >= VERBATIM_MIN_JACCARD_WORDS and gedeeld / len(left | right) >= jaccard:
        return True
    return kleinste >= min_words and gedeeld / kleinste >= containment


def _correct_texts(options: list[str], indices: list[int]) -> set[str]:
    teksten = {" ".join(_words(options[index])) for index in indices if index < len(options)}
    # Getallen zijn geen begrippen: twee rekenvragen met uitkomst 3/5 zijn
    # verschillende vragen.
    return {tekst for tekst in teksten if tekst and as_number(tekst.replace(" ", "/")) is None}


def duplicate_of(draft: ExamDraft, cards: list[PracticeCard]) -> str | None:
    """Waarom deze vraag geen nieuwe vraag is, of None."""
    vraag = _similarity_words(draft.question)
    onderwerp = _object_words(draft.question)
    grens = VERBATIM_LIMIT_MC if draft.kind == "mc" else VERBATIM_LIMIT_OPEN
    mijn_goed = (
        _correct_texts(draft.options, [LETTERS.index(letter.strip().lower()) for letter in draft.correct if letter.strip().lower() in LETTERS])
        if draft.kind == "mc" else set()
    )
    mijn_antwoord = _similarity_words(draft.model_answer)
    mijn_schema = _similarity_words(" ".join(item.criterion for item in draft.rubric))

    for card in cards:
        if card.kind != draft.kind:
            continue
        if _overlaps(vraag, _similarity_words(card.question), grens, grens, VERBATIM_MIN_WORDS):
            return f"lijkt te veel op \"{_short(card.question)}\""
        spec = card.spec or {}
        if draft.kind == "mc":
            hun_goed = _correct_texts(spec.get("options") or [], spec.get("answer") or [])
            if mijn_goed and mijn_goed == hun_goed:
                return f"heeft hetzelfde goede antwoord ({', '.join(sorted(mijn_goed))}) als \"{_short(card.question)}\""
            mijn_zin = set().union(*(_similarity_words(tekst) for tekst in mijn_goed)) if mijn_goed else set()
            hun_zin = set().union(*(_similarity_words(tekst) for tekst in hun_goed)) if hun_goed else set()
            if min(len(mijn_zin), len(hun_zin)) >= CORRECT_MIN_WORDS and len(mijn_zin & hun_zin) / len(mijn_zin | hun_zin) >= CORRECT_SIMILARITY_LIMIT:
                return f"heeft een goed antwoord dat hetzelfde zegt als bij \"{_short(card.question)}\""
            # Het antwoord van de een is het onderwerp van de ander: "which
            # colormap is this? → sequential" en "what defines a sequential
            # colormap?" vragen hetzelfde begrip.
            for antwoorden, andere_vraag in ((hun_goed, draft.question), (mijn_goed, card.question)):
                for antwoord in antwoorden:
                    begrip = _object_words(antwoord)
                    if begrip and len(antwoord.split()) <= CONCEPT_MAX_WORDS and begrip <= _object_words(andere_vraag):
                        return f"vraagt naar hetzelfde begrip ({antwoord}) als \"{_short(card.question)}\""
            ander = _object_words(card.question)
            if draft.template == spec.get("template") and onderwerp and ander:
                if len(onderwerp & ander) / min(len(onderwerp), len(ander)) >= OBJECT_OVERLAP:
                    return f"vraagt hetzelfde over hetzelfde onderwerp als \"{_short(card.question)}\""
        else:
            if _overlaps(mijn_antwoord, _similarity_words(card.reference_answer), ANSWER_SIMILARITY_LIMIT,
                         ANSWER_CONTAINMENT_LIMIT, ANSWER_CONTAINMENT_MIN_WORDS):
                return f"heeft hetzelfde antwoord als \"{_short(card.question)}\""
            hun_schema = _similarity_words(" ".join(item.get("criterion", "") for item in spec.get("rubric") or []))
            if _overlaps(mijn_schema, hun_schema, ANSWER_SIMILARITY_LIMIT, RUBRIC_CONTAINMENT_LIMIT, ANSWER_CONTAINMENT_MIN_WORDS):
                return f"geeft punten voor hetzelfde als \"{_short(card.question)}\""
            ander = _object_words(card.question)
            if draft.template == spec.get("template") and onderwerp and ander and mijn_schema and hun_schema:
                zelfde_onderwerp = len(onderwerp & ander) / min(len(onderwerp), len(ander)) >= OBJECT_OVERLAP
                schema_raakt = len(mijn_schema & hun_schema) / min(len(mijn_schema), len(hun_schema)) >= RUBRIC_OVERLAP_FOR_OBJECT
                if zelfde_onderwerp and schema_raakt:
                    return f"vraagt hetzelfde over hetzelfde onderwerp als \"{_short(card.question)}\""
    return None


def gives_away(draft: ExamDraft) -> str | None:
    """Het antwoord, als het in de vraag zelf staat."""
    vraag = _object_words(draft.question)
    if draft.kind == "open":
        kandidaten = [draft.model_answer]
    else:
        kandidaten = [draft.options[LETTERS.index(letter.strip().lower())] for letter in draft.correct
                      if letter.strip().lower() in LETTERS[: len(draft.options)]]
    for antwoord in kandidaten:
        woorden = _object_words(antwoord)
        if woorden and len(_similarity_words(antwoord)) <= GIVEAWAY_MAX_WORDS and woorden <= vraag:
            return antwoord.strip()
    return None


def off_theme(draft: ExamDraft, plan: SectionPlan) -> bool:
    """Raakt de vraag of zijn antwoord geen enkel woord van het thema?

    Het antwoord telt mee: een scenariovraag beschrijft het symptoom en niet de
    naam van de techniek, en werd zo "buiten thema" terwijl regularisatie het
    antwoord was.
    """
    if not plan.theme_words:
        return False
    # De uitleg ook: een invulvraag over broadcasting noemt het woord zelf niet,
    # zijn uitleg wel.
    tekst = " ".join([
        draft.question, *draft.options, draft.model_answer, draft.explanation,
        *(item.criterion for item in draft.rubric),
    ])
    return not (_distinctive(tekst) & plan.theme_words)


def next_origin(db: Session, course_slug: str) -> str:
    nummers = [
        int(origin[len(ORIGIN_PREFIX):])
        for (origin,) in db.execute(
            select(PracticeCard.origin).where(
                PracticeCard.course_slug == course_slug, PracticeCard.origin.like(f"{ORIGIN_PREFIX}%")
            ).distinct()
        )
        if origin[len(ORIGIN_PREFIX):].isdigit()
    ]
    return f"{ORIGIN_PREFIX}{max(nummers, default=0) + 1}"


def title_for(origin: str) -> str:
    return f"{TITLE_PREFIX} {origin[len(ORIGIN_PREFIX):]}"


# --- de prompt -----------------------------------------------------------------


def topic_usage(plan: SectionPlan, cards: list[PracticeCard]) -> Counter:
    """Hoeveel bestaande vragen elk onderwerp van deze sectie al raken."""
    teksten = [f"{card.question} {card.reference_answer}" for card in cards]
    return Counter({topic: sum(1 for tekst in teksten if covers(tekst, topic)) for topic in plan.topics})


def assign_topics(slots: list[Slot], plan: SectionPlan, material: SectionMaterial, usage: Counter) -> list[tuple[Slot, str]]:
    """Elke plek een onderwerp: het minst gevraagde waar stof voor is.

    Zonder sturing kiest het model per sectie steeds dezelfde handvol begrippen,
    en in een tweede oefententamen zijn die al gevraagd — dan blijven plekken
    leeg. Zware plekken eerst, zodat die het onderwerp met de meeste stof krijgen.
    """
    beschikbaar = [topic for topic in plan.topics if material.per_topic.get(topic)]
    if not beschikbaar:
        return [(slot, "") for slot in slots]
    teller = Counter({topic: usage.get(topic, 0) for topic in beschikbaar})
    toegewezen: list[tuple[Slot, str]] = []
    for slot in sorted(slots, key=lambda item: -item.points):
        if slot.points >= HEAVY_POINTS:
            # Een zware vraag heeft genoeg stof nodig voor vier criteria.
            kandidaten = sorted(beschikbaar, key=lambda topic: (teller[topic], -len(material.per_topic[topic])))
        else:
            kandidaten = sorted(beschikbaar, key=lambda topic: (teller[topic], plan.topics.index(topic)))
        topic = kandidaten[0]
        teller[topic] += 1
        toegewezen.append((slot, topic))
    return toegewezen


def _slot_lines(slots: list[Slot]) -> list[str]:
    teller = Counter(slots)
    return [
        f"- {n}× {slot.label()}"
        for slot, n in sorted(teller.items(), key=lambda item: (item[0].kind != "mc", item[0].points))
    ]


def _section_prompt(
    plan: SectionPlan,
    all_titles: list[str],
    avoid: list[str],
    material: list[Chunk],
    slots: list[Slot],
    focus: str | None = None,
    assignment: list[tuple[Slot, str]] | None = None,
) -> str:
    lines = [
        f"Maak sectie {plan.number} van een nieuw oefententamen: \"{plan.title}\".",
        "",
        "De secties van het tentamen: " + "; ".join(all_titles) + ".",
        f"Blijf binnen het thema van sectie {plan.number}. Wat bij een andere sectie hoort, laat je weg.",
        "",
        "Opbouw — precies deze vragen, niet meer en niet minder:",
        *_slot_lines(slots),
        "",
    ]
    if plan.forms and not focus:
        onderwerp = next((topic for _, topic in assignment or [] if topic), None) or (plan.topics[0] if plan.topics else "")
        lines += [
            "Dit is één vraag met deelvragen, zoals op het tentamen: één situatie met concrete getallen, en "
            "elke deelvraag bouwt daarop voort. Herhaal in elke deelvraag de gegevens die hij nodig heeft.",
            f"De situatie gaat over: {onderwerp}.",
            "De deelvragen, in deze volgorde en in deze vormen:",
            *[f"{index}. {form}" for index, form in enumerate(plan.forms, start=1)],
            "",
        ]
    elif focus:
        lines += [f"Maak deze vraag over: {focus}.", ""]
    elif assignment and all(topic for _, topic in assignment):
        lines += [
            "Maak de vragen over deze onderwerpen, in deze verdeling. Ze zijn gekozen omdat er in het "
            "proeftentamen en eerdere oefententamens nog weinig naar gevraagd is:",
            *[f"- {slot.label()} over: {topic}" for slot, topic in assignment],
            "",
        ]
    else:
        lines += [
            "Onderwerpen die in deze sectie thuishoren. Spreid de vragen erover:",
            *[f"- {topic}" for topic in plan.topics],
            "",
        ]
    lines += [
        "Het proeftentamen staat in de instructie. Neem daarvan de vorm en het niveau over, niet de vragen. "
        "Een vraag die op een vraag uit het proeftentamen lijkt, of die hetzelfde antwoord heeft, wordt "
        "automatisch afgekeurd. Vraag dus naar een ander begrip, of pas hetzelfde begrip toe op iets anders — "
        "niet 'waarom is k-NN non-parametric' maar 'waarom is lineaire regressie parametric'. Stel binnen "
        "deze sectie nooit twee vragen met hetzelfde antwoord.",
        "",
    ]
    gevraagd = []
    for question in plan.original:
        if question.type == "open":
            gevraagd.append(f"- {question.topic}: {' '.join(question.model_answer.split())[:110]}")
        else:
            goed = "; ".join(question.options[LETTERS.index(letter)] for letter in question.answer)
            gevraagd.append(f"- {question.topic}: {goed}")
    if gevraagd:
        lines += ["In deze sectie van het proeftentamen al gevraagd, met het goede antwoord. Gebruik deze "
                  "antwoorden niet opnieuw:", *gevraagd, ""]
    if avoid:
        lines += ["Deze vragen bestaan al. Maak ze niet opnieuw, ook niet in andere woorden:", *[f"- {q}" for q in avoid], ""]
    lines += ["Materiaal:", material_block(material)]
    return "\n".join(lines)


def _client():
    if not settings.openai_api_key or OpenAI is None:
        return None
    return OpenAI(api_key=settings.openai_api_key)


# --- een sectie genereren ------------------------------------------------------


def generate_section(
    db: Session,
    *,
    course_slug: str,
    section_number: int,
    origin: str | None = None,
    client=None,
) -> SectionResult:
    blueprint = course_blueprint(course_slug)
    plans = exam_plans(db, course_slug)
    plan = next((item for item in plans if item.number == section_number), None)
    if plan is None:
        raise ValueError(f"de opbouw heeft geen sectie {section_number}")
    scoring = plan_scoring(plan)
    style = course_style(course_slug)

    origin = origin or next_origin(db, course_slug)
    title = title_for(origin)
    result = SectionResult(
        origin=origin,
        title=title,
        section_number=plan.number,
        section_title=plan.title,
        planned_points=sum(slot.points for slot in plan.slots),
    )

    material = section_material(db, course_slug, plan)
    result.uncovered_topics = material.uncovered
    if material.covered_share < MIN_COVERED_SHARE or not material.chunks:
        zonder = [topic for topic in plan.topic_points if not material.per_topic.get(topic)]
        result.source_note = (
            "voor " + ", ".join(zonder) + " staat nog geen college of leesstof in het corpus; oefen deze "
            "sectie met het proeftentamen en maak hem opnieuw zodra die stof er is"
        )
        result.missing = list(plan.slots)
        return result

    client = client or _client()
    if client is None:
        raise NoBlueprint("er is geen antwoordmodel geconfigureerd om vragen mee te maken")

    by_id = {chunk.id: chunk for chunks in material.per_topic.values() for chunk in chunks}
    by_id |= {chunk.id: chunk for chunk in material.chunks}
    documents = {
        document.id: document
        for document in db.scalars(select(Document).where(Document.id.in_({chunk.document_id for chunk in by_id.values()})))
    }

    bestaande = list(db.scalars(
        select(PracticeCard).where(
            PracticeCard.course_slug == course_slug,
            PracticeCard.kind.in_(["mc", "open"]),
            PracticeCard.disabled.is_(False),
        )
    ))
    seen = {card.question.strip().lower() for card in bestaande}
    # Vergelijken met alles wat al een tentamenvraag is: het proeftentamen,
    # eerdere oefententamens, en wat deze sectie net heeft opgeleverd.
    pool = [card for card in bestaande if card.origin is not None]
    avoid = [
        _short(card.question)
        for card in pool
        if card.origin != blueprint.id and (card.spec or {}).get("section_number") == plan.number
    ]

    # Bij aanvullen tellen de vragen die er al staan: anders raakt een halfvolle
    # sectie te vol, want de opbouw gaat uit van een lege.
    remaining = Counter(plan.slots)
    for card in pool:
        if card.origin == origin and (card.spec or {}).get("section_number") == plan.number:
            slot = Slot(card.kind, card.points or 0.0)
            if remaining[slot] > 0:
                remaining[slot] -= 1
    if not +remaining:
        return result
    positie = db.scalar(
        select(func.max(PracticeCard.position)).where(
            PracticeCard.course_slug == course_slug, PracticeCard.origin == origin
        )
    ) or 0
    main_week = plan.main_weeks[0] if plan.main_weeks else None

    def consider(draft: ExamDraft, repairable: list[tuple] | None) -> None:
        nonlocal positie
        slot = Slot(draft.kind, scoring.choice_points if draft.kind == "mc" else draft.points)
        if remaining[slot] <= 0:
            # Eerst: een vraag waarvoor geen plek meer is hoeft niet nagelopen
            # of hersteld te worden.
            result.rejected.append((draft.question, f"past niet meer in de opbouw: er zijn al genoeg van {slot.label()}"))
            return
        reden = accept_exam_draft(draft, by_id, seen, repairable, scoring=scoring, style=style)
        if reden is not None:
            if reden != DUPLICATE or repairable is not None:
                result.rejected.append((draft.question, reden))
            return
        reden = duplicate_of(draft, pool)
        if reden is None and (weggegeven := gives_away(draft)):
            reden = f"de vraag noemt het antwoord al ({weggegeven[:40]})"
        if reden is None and off_theme(draft, plan):
            reden = f"hoort niet bij het thema van sectie {plan.number} ({plan.title})"
        if reden is not None:
            if repairable is not None:
                repairable.append((draft, reden))
            result.rejected.append((draft.question, reden))
            return

        remaining[slot] -= 1
        positie += 1
        chunk = source_chunk(draft, by_id)
        card = build_card(
            draft, chunk, documents.get(chunk.document_id), course_slug,
            f"{title}{SEPARATOR}{plan.number} {plan.title}",
            choice_points=scoring.choice_points,
        )
        card.origin = origin
        card.position = positie
        card.week = main_week
        card.spec = {
            **card.spec,
            "exam": origin,
            "based_on": blueprint.id,
            "section_number": plan.number,
            "section": f"{plan.number} {plan.title}",
        }
        db.add(card)
        seen.add(card.question.lower())
        pool.append(card)
        result.created.append(card)

    def ask(prompt: str, instructions: str) -> list[ExamDraft]:
        return client.responses.parse(
            model=settings.openai_answer_model,
            instructions=instructions,
            input=prompt,
            text_format=ExamBatch,
        ).output_parsed.cards

    def open_slots() -> list[Slot]:
        return [slot for slot, n in remaining.items() for _ in range(n)]

    instructions = exam_instructions(course_slug, scoring, style)
    all_titles = [f"{item.number} {item.title}" for item in plans]

    sectiekaarten = [card for card in pool if (card.spec or {}).get("section_number") == plan.number]
    verdeling = assign_topics(open_slots(), plan, material, topic_usage(plan, sectiekaarten))

    te_herstellen: list[tuple] = []
    for draft in ask(_section_prompt(plan, all_titles, avoid, material.chunks, open_slots(), assignment=verdeling), instructions):
        consider(draft, te_herstellen)

    if te_herstellen and open_slots():
        herkansing = {draft.question for draft, _ in te_herstellen}
        result.rejected = [item for item in result.rejected if item[0] not in herkansing]
        prompt = ["Verbeter deze vragen.", ""]
        for index, (draft, reden) in enumerate(te_herstellen, start=1):
            prompt += [f"--- vraag {index}", f"afgekeurd omdat: {reden}", draft.model_dump_json(indent=1), ""]
        prompt += ["Materiaal:", material_block(material.chunks)]
        hersteld = ask("\n".join(prompt), repair_instructions(scoring))
        for draft in hersteld:
            consider(draft, None)
        for draft, reden in te_herstellen[len(hersteld):]:
            result.rejected.append((draft.question, reden))

    # De lichte plekken die nog open zijn. Het model maakt anders precies de
    # vraag opnieuw die net als herhaling werd afgekeurd — het weet niet dát,
    # en niet waaróm. Die gaan dus mee in de lijst "maak dit niet".
    for _ in range(FILL_ROUNDS):
        licht = [slot for slot in open_slots() if slot.points < HEAVY_POINTS]
        if not licht:
            break
        herhalingen = [
            f"{_short(vraag)} (afgekeurd: {reden[:60]})"
            for vraag, reden in result.rejected
            if reden.startswith(("lijkt te veel", "heeft hetzelfde", "vraagt ", "geeft punten", "heeft een goed", "vraag bestaat"))
        ]
        gemaakt = avoid + [_short(card.question) for card in result.created] + herhalingen
        sectiekaarten = [card for card in pool if (card.spec or {}).get("section_number") == plan.number]
        # Wat net is afgekeurd telt ook als gevraagd, anders krijgt het volgende
        # rondje hetzelfde onderwerp toegewezen.
        gebruik = topic_usage(plan, sectiekaarten)
        for vraag, _ in result.rejected:
            for topic in plan.topics:
                if covers(vraag, topic):
                    gebruik[topic] += 1
        verdeling = assign_topics(licht, plan, material, gebruik)
        for draft in ask(_section_prompt(plan, all_titles, gemaakt, material.chunks, licht, assignment=verdeling), instructions):
            consider(draft, None)

    # Een zware open vraag heeft vier criteria met elk een eigen citaat nodig,
    # en dat lukt zelden uit een brede greep stof. Hij krijgt de stof van één
    # goed gedekt onderwerp — niet dat van de zware vraag uit het proeftentamen,
    # want daar komt alleen een herformulering uit.
    zwaar_in_origineel = {question.topic for question in plan.original if question.type == "open" and question.points >= HEAVY_POINTS}
    gebruik = topic_usage(plan, [card for card in pool if (card.spec or {}).get("section_number") == plan.number])
    kandidaten = [
        topic for topic, chunks in sorted(material.per_topic.items(), key=lambda item: (gebruik.get(item[0], 0), -len(item[1])))
        if chunks and topic not in zwaar_in_origineel
    ]
    for slot in [slot for slot in open_slots() if slot.points >= HEAVY_POINTS]:
        for topic in kandidaten[:HEAVY_ATTEMPTS]:
            if remaining[slot] <= 0:
                break
            focus: list[Chunk] = []
            budget = MAX_FOCUS_CHARS
            for chunk in material.per_topic[topic]:
                if len(chunk.text) <= budget:
                    focus.append(chunk)
                    budget -= len(chunk.text)
            gemaakt = avoid + [_short(card.question) for card in result.created]
            herstel: list[tuple] = []
            for draft in ask(_section_prompt(plan, all_titles, gemaakt, focus, [slot], focus=topic), instructions):
                consider(draft, herstel)
            # Een zware vraag struikelt meestal over één citaat dat net niet
            # letterlijk is; dat herstelt het model met de reden ernaast wel.
            if herstel and remaining[slot] > 0:
                prompt = ["Verbeter deze vraag.", ""]
                for draft, reden in herstel:
                    prompt += [f"afgekeurd omdat: {reden}", draft.model_dump_json(indent=1), ""]
                prompt += ["Materiaal:", material_block(focus)]
                for draft in ask("\n".join(prompt), repair_instructions(scoring)):
                    consider(draft, None)
        kandidaten = kandidaten[HEAVY_ATTEMPTS:] + kandidaten[:HEAVY_ATTEMPTS]

    result.missing = open_slots()
    if result.created:
        db.commit()
    return result


def generate_practice_exam(db: Session, course_slug: str, *, client=None) -> list[SectionResult]:
    """Alle secties van één nieuw oefententamen, achter elkaar."""
    origin = next_origin(db, course_slug)
    return [
        generate_section(db, course_slug=course_slug, section_number=plan.number, origin=origin, client=client)
        for plan in exam_plans(db, course_slug)
    ]
