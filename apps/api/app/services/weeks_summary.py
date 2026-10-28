"""De samenvatting van een week.

Niet via retrieval maar rechtstreeks uit SQL, om dezelfde reden als bij de
oefendecks: je wil niet de semantisch beste fragmenten maar *alles* wat die
week behandelt. Een samenvatting die de helft van het materiaal niet gezien
heeft is erger dan geen samenvatting, want je merkt het niet.

Wat er ontbreekt wordt daarom geteld en meegegeven: past de week niet in één
prompt, dan staat erbij hoeveel er buiten viel.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Chunk, Course, Document, WeekSummary
from app.services.spoilers import is_hidden, open_assignment_weeks
from app.services.terms import KEEP_TERMS, keep_terms_in
from app.services.weeks import WeekScope, week_scope

try:  # pragma: no cover — de app moet importeerbaar blijven zonder de SDK
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


logger = logging.getLogger(__name__)

# Ruim genoeg voor twee colleges plus een paar hoofdstukken, en nog steeds een
# prompt die in één keer weg kan.
MAX_SOURCE_CHARS = 120_000


class NoWeekMaterial(ValueError):
    """Deze week heeft geen materiaal om samen te vatten."""


class Topic(BaseModel):
    label: str = Field(description="Het college of hoofdstuk, zoals het in het materiaal heet")
    covers: str = Field(description="Wat het behandelt, twee of drie zinnen")
    where: str = Field(description="Waar het staat: slides of pagina's")


class Concept(BaseModel):
    term: str = Field(description="Het begrip")
    meaning: str = Field(description="Eén regel: wat het is, in je eigen woorden")


class Symbol(BaseModel):
    symbol: str = Field(description="Het symbool, in LaTeX zonder dollartekens")
    meaning: str = Field(description="Waar het voor staat, in een paar woorden")


class Formula(BaseModel):
    name: str = Field(description="Hoe de formule heet, zoals het materiaal hem noemt")
    latex: str = Field(description="De formule in LaTeX, zonder dollartekens eromheen")
    when: str = Field(description="Wanneer je hem gebruikt, één regel")
    symbols: list[Symbol] = Field(
        default_factory=list, description="Elk symbool uit de formule, met waar het voor staat"
    )


class SummaryDraft(BaseModel):
    thread: str = Field(description="De rode draad van de week, drie tot vijf zinnen")
    topics: list[Topic] = Field(default_factory=list)
    formulas: list[Formula] = Field(default_factory=list)
    concepts: list[Concept] = Field(default_factory=list)
    skills: list[str] = Field(
        default_factory=list,
        description="Handelingen die je na deze week moet kunnen uitvoeren, elk één regel",
    )


INSTRUCTIONS = (
    "Je vat een studieweek samen voor een student datascience, uit het aangeboden "
    "materiaal. De samenvatting is geen vervanging van de stof maar een kaart "
    "ervan: hij moet je in tien minuten laten zien waar deze week over gaat, "
    "zodat je daarna gericht leest.\n"
    "\n"
    "thread: de rode draad. Waarom staan deze onderwerpen bij elkaar, en hoe "
    "bouwen ze op elkaar voort? Drie tot vijf zinnen, geen opsomming.\n"
    "topics: de blokken waar deze week uit bestaat, hooguit acht. Groepeer op "
    "onderwerp, niet per slide: 'toetsen voor twee steekproeven' is één blok, "
    "ook als het over acht slides loopt. Zeg erbij waar het staat.\n"
    "formulas: het formuleblad van deze week — de formules die je op een "
    "schriftelijk tentamen nodig hebt, hooguit tien. Per formule: hoe hij heet, "
    "de formule in LaTeX (zonder dollartekens), wanneer je hem gebruikt, en wat "
    "élk symbool erin betekent. Alleen formules die in het materiaal van déze "
    "week staan; geen formule zonder uitleg van de symbolen. Schrijf in de náám "
    "geen symbolen maar woorden ('bij bekende standaardafwijking', niet "
    "'sigma bekend'): een los symbool in een kop komt er verminkt uit.\n"
    "concepts: de begrippen die je moet kunnen uitleggen. Eén regel per begrip, "
    "in gewone taal — geen definitie overschrijven maar zeggen wat het ís.\n"
    "skills: de handelingen die je na deze week moet kunnen uitvoeren, zo "
    "concreet mogelijk ('een gepoolde variantie uitrekenen en daarmee toetsen of "
    "twee gemiddelden verschillen'), niet 'begrip van hypothesetoetsen'.\n"
    "\n"
    f"Schrijf in het Nederlands. {KEEP_TERMS} Zet formules tussen $...$. Verzin "
    "niets wat niet in het materiaal staat; is een onderwerp maar half behandeld, "
    "zeg dat dan."
)


# Hooguit zoveel formules per week. Meer is geen formuleblad meer maar een
# tweede boek, en dan sla je het over.
MAX_FORMULAS = 10


def formula_problem(formula: "Formula", material: list[str] | None = None) -> str | None:
    """De reden waarom deze formule niet op het formuleblad hoort, of None.

    Alleen de vórm wordt gecontroleerd, en dat is met opzet. Waar een kaart of
    een voorbeeld op een letterlijk citaat rust, kan dat hier niet: de weekkaart
    is Nederlands en de slides zijn Engels, dus "Kleinste-kwadraten schatters"
    staat nergens in het materiaal. Een eerdere versie controleerde de naam
    tegen de stof en gooide daardoor dertien van de vijftien goede formules weg.

    Wat wél telt: het model krijgt uitsluitend de fragmenten van déze week te
    zien, dus de herkomst is door de invoer begrensd in plaats van door een
    controle achteraf. `material` blijft in de aanroep staan omdat hij bij een
    eentalig vak alsnog bruikbaar zou zijn.
    """
    if not formula.latex.strip():
        return "er staat geen formule bij"
    if not [symbol for symbol in formula.symbols if symbol.symbol.strip() and symbol.meaning.strip()]:
        return "de symbolen worden niet uitgelegd"
    if not formula.when.strip():
        return "er staat niet bij wanneer je hem gebruikt"
    return None


# Voor een vak waarvan het tentamen geen code vraagt. Zonder dit schreef de
# weekkaart van SSO veertien vaardigheden op die allemaal met `lm()`, `drop1()`
# of `predict()` begonnen — precies wat op dat tentamen niet gevraagd wordt.
NO_CODE_ADDENDUM = (
    "\n\n"
    "Let op: het tentamen van dit vak is schriftelijk en vraagt géén R- of "
    "Python-code. Schrijf vaardigheden daarom als handelingen die je met de hand "
    "of op papier doet ('de toetsingsgrootheid uitrekenen en aan de kritieke "
    "waarde toetsen', 'uit de uitvoer aflezen of de helling significant is'), "
    "niet als commando's — dus niet 'fit met lm(y ~ x)' of 'gebruik "
    "drop1(..., test=\"F\")'. Uitvoer van software mag je wél laten interpreteren; "
    "het gaat erom dat de student hem kan lézen, niet kan tikken. Besteed de "
    "ruimte die je daarmee wint aan het formuleblad."
)


# Voor een vak waarvan het tentamen codefragmenten laat lezen maar niet laat
# schrijven. Zo zei de docent van SSO deel 2 het bij college 8: "wat is de
# uitvoer van dit fragment" kan komen, een vergeten komma wordt je niet
# aangerekend.
READ_CODE_ADDENDUM = (
    "\n\n"
    "Let op: het tentamen van dit vak is schriftelijk. Het kan een codefragment "
    "laten zien en vragen wat de uitvoer is, maar het vraagt niet om exacte "
    "syntax uit je hoofd te schrijven. Neem dus vaardigheden op als 'de uitvoer "
    "van een PuLP-model voorspellen' of 'uit de code aflezen welke beperking "
    "wordt toegevoegd', maar niet 'schrijf de aanroep van ...'. Het gaat erom dat "
    "de student code kan lezen en voorspellen wat hij doet; syntax precies "
    "kennen hoort er niet bij."
)


def instructions_for(db: Session, course_slug: str) -> str:
    """De instructie voor dit vak, naar hoe het tentamen naar code vraagt."""
    course = db.get(Course, course_slug)
    setting = (course.study or {}).get("code") if course is not None else None
    if setting == "none":
        return INSTRUCTIONS + NO_CODE_ADDENDUM
    if setting == "read":
        return INSTRUCTIONS + READ_CODE_ADDENDUM
    return INSTRUCTIONS


@dataclass
class WeekMaterial:
    scope: WeekScope
    chunks: list[Chunk]
    total: int

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for chunk in self.chunks:
            digest.update(chunk.id.encode())
        return digest.hexdigest()


def _hidden_provider(db: Session):
    return open_assignment_weeks(db)


def week_material(db: Session, course_slug: str, week: int, *, fit: bool = True) -> WeekMaterial:
    """Alle chunks van deze week: eigen documenten eerst, dan de leesstof.

    De colleges gaan voorop omdat zij bepalen wát er die week behandeld is; het
    boek vult aan. Past niet alles in het budget, dan valt de staart van het
    boek af en niet het college.

    `fit=False` slaat dat uitdunnen over. De uitdunning bestaat omdat een
    samenvatting in één prompt moet passen; wie per onderwerp filtert heeft dat
    plafond niet nodig en wordt er juist door gehinderd. Bij FDS week 4 viel een
    paper van twaalf fragmenten er volledig uit, waardoor "link prediction"
    stof leek te missen die er wel was.
    """
    scope = week_scope(db, course_slug, week)
    hidden = _hidden_provider(db)

    own = list(
        db.execute(
            select(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .where(
                Document.course_slug == course_slug,
                Document.ingestion_status == "indexed",
                Document.week == week,
            )
            .order_by(Document.source_path, Chunk.chunk_index)
        )
    )

    reading: list[tuple[Chunk, Document]] = []
    for span in scope.spans:
        reading.extend(
            db.execute(
                select(Chunk, Document)
                .join(Document, Chunk.document_id == Document.id)
                .where(
                    Chunk.document_id == span.document_id,
                    Chunk.page_end >= span.page_start,
                    Chunk.page_start <= span.page_end,
                )
                .order_by(Chunk.chunk_index)
            )
        )

    seen: set[str] = set()
    own_chunks: list[Chunk] = []
    reading_chunks: list[Chunk] = []
    for bron, doel in ((own, own_chunks), (reading, reading_chunks)):
        for chunk, document in bron:
            if chunk.id in seen:
                continue
            # Dezelfde spoilerregel als bij een vraag: een uitwerking uit een
            # week met een open opdracht hoort ook niet in een samenvatting.
            if is_hidden(document.course_slug, document.doc_kind, document.week, hidden):
                continue
            seen.add(chunk.id)
            doel.append(chunk)
    ordered = own_chunks + reading_chunks

    chunks = _fit(own_chunks, reading_chunks) if fit else ordered
    return WeekMaterial(scope=scope, chunks=chunks, total=len(ordered))


def _fit(lectures: list[Chunk], reading: list[Chunk]) -> list[Chunk]:
    """Colleges compleet, de leesstof gelijkmatig uitgedund als het niet past.

    Afkappen van achteren zou het laatste hoofdstuk van een week volledig laten
    verdwijnen zonder dat de samenvatting doorheeft dat het bestond. Een
    gelijkmatige greep laat elk hoofdstuk aan bod komen; dat de samenvatting
    dan grofmaziger is, staat eronder.
    """
    binnen: list[Chunk] = []
    budget = MAX_SOURCE_CHARS
    for chunk in lectures:
        if binnen and len(chunk.text) > budget:
            break
        binnen.append(chunk)
        budget -= len(chunk.text)

    if not reading or budget <= 0:
        return binnen

    nodig = sum(len(chunk.text) for chunk in reading)
    stap = 1 if nodig <= budget else max(2, round(nodig / budget))
    for chunk in reading[::stap]:
        if len(chunk.text) > budget:
            break
        binnen.append(chunk)
        budget -= len(chunk.text)
    return binnen


def _client():
    if not settings.openai_api_key or OpenAI is None:
        return None
    return OpenAI(api_key=settings.openai_api_key)


def _prompt(material: WeekMaterial, course_slug: str, week: int) -> str:
    lines = [f"Vat week {week} van {course_slug} samen.", ""]
    if material.scope.topics:
        # Uit course.yml: de studiewijzer weet welke onderwerpen erbij horen,
        # ook als het materiaal ze anders noemt.
        lines += ["Volgens de studiewijzer gaat deze week over:"]
        lines += [f"- {topic}" for topic in material.scope.topics]
        lines.append("")
    lines.append("Materiaal:")
    for chunk in material.chunks:
        lines.append(f"\n[{chunk.section_path or 'zonder sectie'} · p. {chunk.page_start}]\n{chunk.text}")
    return "\n".join(lines)


def build_summary(
    db: Session, *, course_slug: str, week: int, client=None
) -> WeekSummary:
    material = week_material(db, course_slug, week)
    if not material.chunks:
        raise NoWeekMaterial(
            f"week {week} van {course_slug} heeft geen geïndexeerd materiaal"
            + (f" — {'; '.join(material.scope.unresolved)}" if material.scope.unresolved else "")
        )

    client = client or _client()
    if client is None:
        raise NoWeekMaterial("er is geen antwoordmodel geconfigureerd om samen te vatten")

    draft: SummaryDraft = client.responses.parse(
        model=settings.openai_answer_model,
        instructions=instructions_for(db, course_slug),
        input=_prompt(material, course_slug, week),
        text_format=SummaryDraft,
    ).output_parsed
    draft = SummaryDraft.model_validate(keep_terms_in(draft.model_dump()))

    # Het formuleblad wordt nagelopen voordat het wordt bewaard; wat afvalt
    # wordt met reden gemeld in plaats van stil weggelaten.
    teksten = [chunk.text for chunk in material.chunks]
    problems: list[str] = []
    goede: list[Formula] = []
    for formula in draft.formulas:
        reason = formula_problem(formula, teksten)
        if reason:
            problems.append(f"{formula.name}: {reason}")
        elif len(goede) >= MAX_FORMULAS:
            problems.append(f"{formula.name}: meer dan {MAX_FORMULAS} formules past niet op één blad")
        else:
            goede.append(formula)
    draft.formulas = goede

    summary = db.get(WeekSummary, (course_slug, week)) or WeekSummary(
        course_slug=course_slug, week=week
    )
    content = draft.model_dump()
    content["problems"] = problems
    summary.content = content
    summary.source_fingerprint = material.fingerprint
    summary.chunks_used = len(material.chunks)
    summary.chunks_total = material.total
    db.add(summary)
    db.commit()
    db.refresh(summary)
    return summary


def is_stale(db: Session, summary: WeekSummary) -> bool:
    """Is het materiaal veranderd sinds deze samenvatting is gemaakt?"""
    material = week_material(db, summary.course_slug, summary.week)
    return material.fingerprint != summary.source_fingerprint
