"""Kaarten maken uit de tekst van één sectie.

Het model stelt voor, de interpreter beslist. Elke voorgestelde kaart wordt
uitgevoerd voordat hij wordt opgeslagen; draait de referentie-uitdrukking
niet, dan gaat de kaart weg vóór iemand hem ziet. Zo lekt een verzonnen
antwoord niet je oefenset in — dezelfde discipline als bij de evalset.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Chunk, PracticeCard
from app.services.practice.decks import section_chunks
from app.services.practice.sandbox import evaluate, tolerance_for
from app.services.practice.validation import (
    SetupRejected,
    computes_nothing,
    giveaway_terms,
    validate_setup,
)
from app.services.terms import KEEP_TERMS

try:  # pragma: no cover — de app moet importeerbaar blijven zonder de SDK
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


logger = logging.getLogger(__name__)

MAX_CARDS_PER_CALL = 20

# Getallen in de uitwerking. De Nederlandse komma en de LaTeX-punt komen door
# elkaar voor, dus allebei; `{,}` is hoe je in LaTeX een decimaalkomma zet.
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\s*\{,\}\s*|[.,])?\d*")


def numbers_in(text: str) -> list[float]:
    found: list[float] = []
    for raw in _NUMBER_RE.findall(text):
        try:
            found.append(float(raw.replace("{,}", ".").replace(",", ".").replace(" ", "").rstrip(".")))
        except ValueError:
            continue
    return found


# Een uitwerking hoort het getal af te leiden uit de gegevens. Verwijst hij naar
# de uitdrukking ("volgens de gegeven uitdrukking is $\\chi^2 = (x-y)^2/x$"), dan
# praat hij de code na en klopt de afleiding juist niet — dat was precies hoe de
# twee kapotte kaarten uit de eerste ronde eruitzagen.
_CODE_IN_PROSE = ("uitdrukking", "np.", "stats.", "python", "rankdata", "ddof")


def narrates_the_code(explanation: str) -> str | None:
    """Geef het woord dat verraadt dat de uitwerking naar de code wijst."""
    lowered = explanation.lower()
    return next((woord for woord in _CODE_IN_PROSE if woord in lowered), None)


def _agrees(value: float, expected: float, tolerance: float) -> bool:
    return abs(value - expected) <= tolerance * abs(expected) or (expected == 0.0 and value == 0.0)


class CardDraft(BaseModel):
    chunk_id: str = Field(description="Het chunk_id uit het aangeboden materiaal, letterlijk overgenomen")
    setup: str = Field(description="Python die de fixture bouwt; alleen toewijzingen met np en pd")
    question: str = Field(description="De vraag, met de fixture in woorden beschreven")
    reference_answer: str = Field(description="Eén uitdrukking die het antwoord oplevert")
    explanation: str = Field(default="", description="Niet gebruikt bij codekaarten")


class CardBatch(BaseModel):
    cards: list[CardDraft] = Field(default_factory=list)


class StatsDraft(BaseModel):
    chunk_id: str = Field(description="Het chunk_id uit het aangeboden materiaal, letterlijk overgenomen")
    setup: str = Field(description="De gegevens als Python-toewijzingen; alleen np, geen imports")
    question: str = Field(description="Het verhaal, het niveau, en welke grootheid gevraagd wordt")
    reference_answer: str = Field(description="Eén uitdrukking die precies die grootheid als getal oplevert")
    explanation: str = Field(description="De volledige uitwerking: H0/H1, toetsingsgrootheid, verdeling, conclusie")
    computed_value: float = Field(
        description="Het getal waar je in de uitwerking op uitkomt; moet gelijk zijn aan wat reference_answer oplevert"
    )


class StatsBatch(BaseModel):
    cards: list[StatsDraft] = Field(default_factory=list)


@dataclass
class GenerationReport:
    created: list[PracticeCard] = field(default_factory=list)
    # (vraag of opzet, reden van afkeuring)
    rejected: list[tuple[str, str]] = field(default_factory=list)

    def as_lines(self) -> list[str]:
        lines = [f"aangemaakt: {len(self.created)}", f"afgekeurd: {len(self.rejected)}"]
        for label, reason in self.rejected:
            lines.append(f"  {label[:60]}: {reason}")
        return lines


class NoSourceMaterial(ValueError):
    """Deze sectie heeft geen tekst om vragen uit te maken."""


CODE_INSTRUCTIONS = (
    "Je maakt oefenkaarten voor een student datascience, uit het aangeboden materiaal.\n"
    "Elke kaart toetst één handeling met NumPy of pandas die in dat materiaal staat.\n"
    "\n"
    "setup: Python die de fixture bouwt. Alleen toewijzingen, alleen `np` en `pd` "
    "(die staan al klaar, importeer ze niet). Houd hem klein en concreet: een array "
    "van 3×4 is genoeg, een dataframe van vier rijen ook.\n"
    "question: beschrijf in woorden wát je wil weten — het resultaat, niet de weg "
    "ernaartoe. Noem nooit de functie, methode of parameter die in het antwoord "
    "staat: bij antwoord `np.sort(x)` vraag je niet \"wat geeft np.sort(x)?\" maar "
    "\"hoe krijg je x oplopend gesorteerd zonder x zelf te wijzigen?\". De student "
    "ziet de opzetcode, dus de namen van de fixture mag je wel noemen.\n"
    "reference_answer: precies één uitdrukking die het antwoord oplevert. Geen "
    "toewijzing, geen print, geen meerdere regels. Hij moet een waarde teruggeven.\n"
    "chunk_id: het id van het fragment waar deze vraag op steunt, letterlijk overgenomen.\n"
    "\n"
    "Varieer de handelingen; maak niet vijf keer dezelfde vraag met een ander getal. "
    "Verzin niets wat niet in het materiaal staat. Schrijf de vraag in het Nederlands. "
    f"{KEEP_TERMS}"
)

# Het tentamen vraagt niet om afleidingen maar om toetsen uitvoeren. Een kaart
# is daarom een compleet toetsprobleem: gegevens, vraag, één getal terug, en
# een uitwerking die laat zien hoe je aan dat getal komt.
STATS_INSTRUCTIONS = (
    "Je maakt oefenkaarten voor een student die zich voorbereidt op een schriftelijk "
    "tentamen statistiek. Dat tentamen vraagt geen afleidingen en geen integralen: "
    "het vraagt om toetsen úitvoeren op concrete getallen. Elke kaart is dus één "
    "toetsprobleem, van hypothese tot conclusie.\n"
    "\n"
    "Kies de toets die bij het aangeboden materiaal past en varieer over de kaarten: "
    "binomiaaltoets, z-toets voor één gemiddelde of één proportie, t-toets voor één "
    "steekproef, t-toets voor gepaarde waarnemingen, t-toets voor twee onafhankelijke "
    "steekproeven met gelijke varianties (gepoold), diezelfde toets met ongelijke "
    "varianties (Welch), toets voor twee proporties, tekentoets, Wilcoxon "
    "signed-rank-toets, Wilcoxon rank-sum-toets, chi-kwadraattoets. Maak niet tien "
    "keer dezelfde toets.\n"
    "\n"
    "setup: de gegevens als Python-toewijzingen. Alleen `np` (staat klaar, importeer "
    "hem niet), geen aanroepen naar iets anders. Bij een rangtoets geef je de "
    "waarnemingen zelf, anders de samenvattende getallen (aantal, gemiddelde, "
    "standaardafwijking, aantal successen). Houd ze klein en met de hand te "
    "verwerken: n tussen 10 en 60, hooguit twee decimalen.\n"
    "question: het verhaal in gewone woorden — waar komen de getallen vandaan en wat "
    "is de bewering — plus of er eenzijdig of tweezijdig getoetst wordt, het "
    "significantieniveau, en precies wélke grootheid je moet opgeven. Vraag altijd om "
    "één getal. Noem nooit de naam van een Python-functie.\n"
    "Vraag om de toetsingsgrootheid of om een kritieke waarde. Een p-waarde vraag je "
    "alleen als hij uit de standaardnormale verdeling komt: uit een t-tabel of een "
    "chi-kwadraattabel lees je geen p-waarde af, alleen of je erboven zit.\n"
    "reference_answer: één uitdrukking die precies die grootheid als getal oplevert. "
    "`np` en `stats` (scipy.stats) staan klaar. Reken de toetsingsgrootheid liever "
    "met de formule uit dan met een kant-en-klare functie, zodat hij precies "
    "overeenkomt met wat de student met de hand doet; gebruik `stats` vooral voor "
    "kritieke waarden en overschrijdingskansen. Rangen zet je met "
    "`stats.rankdata`, nooit met argsort: die deelt gelijke waarden verkeerd in. "
    "De uitdrukking moet iets uitrekenen — een getal dat al in de opzet staat "
    "teruggeven is geen opgave.\n"
    "computed_value: het getal waar je in de uitwerking op uitkomt. Reken de "
    "uitdrukking eerst zelf na en schrijf dan pas de uitwerking; wijkt je "
    "handberekening af van wat de uitdrukking oplevert, dan wordt de kaart "
    "weggegooid.\n"
    "explanation: de uitwerking zoals je hem op het tentamen opschrijft, in het "
    "Nederlands, in vier stappen: (1) H0 en H1 en het niveau, (2) de "
    "toetsingsgrootheid — de formule, de ingevulde getallen, de uitkomst, (3) de "
    "nulverdeling met vrijheidsgraden en het kritieke gebied of de p-waarde, (4) de "
    "conclusie in woorden over de oorspronkelijke bewering. Zet formules tussen "
    "$...$ zodat ze als formule worden weergegeven. Het getal uit stap 2 moet "
    "letterlijk in de tekst staan en gelijk zijn aan computed_value. Schrijf de "
    "uitwerking zoals op papier: geen Python, geen functienamen, en geen verwijzing "
    "naar de uitdrukking — alleen de formule met de getallen erin.\n"
    f"{KEEP_TERMS}\n"
    "chunk_id: het id van het fragment waar deze toets op steunt, letterlijk overgenomen.\n"
    "\n"
    "Kies de getallen zo dat de opgave iets laat zien: een toetsingsgrootheid van "
    "precies nul, of twee steekproeven met exact hetzelfde gemiddelde, leert niets. "
    "Bij een rangtoets zet je waarnemingen die allemaal van elkaar verschillen, "
    "zodat er geen gedeelde rangen zijn.\n"
    "\n"
    "Verzin geen toetsen die niet in het materiaal voorkomen."
)


@dataclass(frozen=True)
class _KindSpec:
    instructions: str
    batch_model: type[BaseModel]
    noun: str


KIND_SPECS: dict[str, _KindSpec] = {
    "code": _KindSpec(CODE_INSTRUCTIONS, CardBatch, "oefenkaarten"),
    "stats": _KindSpec(STATS_INSTRUCTIONS, StatsBatch, "toetsopgaven"),
}


DUPLICATE = "vraag bestaat al in dit deck"


class UnknownKind(ValueError):
    """Deze kaartsoort bestaat niet."""


# Bijna elke afkeuring is een mechanische fout waar het model zelf overheen kan:
# een importregel in de opzet, het antwoord in de vraag, of een handberekening
# die niet uitkomt op wat de uitdrukking geeft. De reden gaat terug naar het
# model in plaats van dat de kaart wordt weggegooid.
REPAIR_INSTRUCTIONS = (
    "De opgaven hieronder zijn afgekeurd. Bij elke staat waarom. Verbeter ze en "
    "lever ze in hetzelfde formaat terug, met dezelfde chunk_id.\n"
    "\n"
    "Schrijf nooit een importregel: `np` en `stats` staan al klaar. De vraag mag "
    "de naam van geen enkele functie of parameter uit het antwoord noemen. De "
    "uitdrukking moet iets uitrekenen — een getal dat al in de opzet staat "
    "teruggeven is geen opgave.\n"
    "\n"
    "Wijkt jouw handberekening af van wat de uitdrukking oplevert, dan klopt één "
    "van de twee niet. Is de uitdrukking de verkeerde formule voor de gevraagde "
    "toets, verbeter dan de uitdrukking; anders zoek je de rekenfout in je "
    "tussenstappen op. De uitwerking moet het getal zélf afleiden uit de gegevens. "
    "Hem overschrijven zonder de afleiding te repareren mag niet, en verwijzen "
    "naar 'de gegeven uitdrukking', naar Python of naar een functienaam ook niet: "
    "de student ziet alleen getallen en formules.\n"
    "\n"
    "computed_value moet gelijk zijn aan wat de uitdrukking oplevert, en dat getal "
    "moet letterlijk in de uitwerking staan."
)


def _repair_prompt(failures: list[tuple]) -> str:
    lines = ["Verbeter deze opgaven.", ""]
    for index, (draft, reden) in enumerate(failures, start=1):
        lines += [
            f"--- opgave {index}",
            f"afgekeurd omdat: {reden}",
            f"chunk_id={draft.chunk_id}",
            f"opzet:\n{draft.setup}",
            f"vraag: {draft.question}",
            f"uitdrukking: {draft.reference_answer}",
            f"jouw uitwerking:\n{getattr(draft, 'explanation', '')}",
            "",
        ]
    return "\n".join(lines)


def _build_prompt(chunks: list[Chunk], count: int, noun: str, bestaand: list[str]) -> str:
    lines = [f"Maak {count} {noun} uit dit materiaal.", ""]
    if bestaand:
        # Zonder dit levert "Meer kaarten" vooral nog een keer dezelfde toets:
        # het model kent zijn eigen vorige ronde niet.
        lines += [
            "Deze vragen staan al in dit deck. Maak andere — een andere toets of "
            "een andere grootheid, niet dezelfde vraag met andere getallen:",
        ]
        lines += [f"- {vraag}" for vraag in bestaand]
        lines.append("")
    lines.append("Materiaal:")
    for chunk in chunks:
        lines.append(f"\nchunk_id={chunk.id}\n{chunk.text}")
    return "\n".join(lines)


def answer_client():
    """Het model waarmee kaarten worden gemaakt, of None zonder sleutel."""
    if not settings.openai_api_key or OpenAI is None:
        return None
    return OpenAI(api_key=settings.openai_api_key)


def _accept(
    draft,
    by_id: dict[str, Chunk],
    seen: set[str],
    kind: str,
    repairable: list[tuple] | None = None,
) -> str | None:
    """Geef de reden van afkeuring, of None als de kaart deugt.

    Wat in `repairable` belandt gaat met die reden terug naar het model; alleen
    een kaart die naar niet-aangeboden materiaal wijst of die er al is valt daar
    niet onder, want daar valt niets aan te verbeteren.
    """
    def herstelbaar(draft, reden: str) -> str:
        if repairable is not None:
            repairable.append((draft, reden))
        return reden
    if draft.chunk_id not in by_id:
        return "verwijst naar een fragment dat niet is aangeboden"
    if not draft.question.strip() or not draft.reference_answer.strip():
        return "vraag of antwoord is leeg"
    if draft.question.strip().lower() in seen:
        return DUPLICATE
    if computes_nothing(draft.reference_answer):
        return herstelbaar(draft, "het referentieantwoord rekent niets uit; het staat al in de opzet")
    try:
        validate_setup(draft.setup)
    except SetupRejected as exc:
        return herstelbaar(draft, f"opzet geweigerd: {exc}")

    # Een vraag die het antwoord bevat is geen oefening maar overtypen. Dit
    # met de prompt hopen op te lossen bleek niet genoeg: vijf van de zes
    # kaarten in de eerste echte ronde noemden gewoon `np.sort(x)`.
    # Namen van één of twee letters tellen niet mee: `stats.binomtest(k=..,
    # n=.., p=..)` zou anders elke vraag afkeuren die het woord "p-waarde"
    # bevat. Wat een antwoord echt weggeeft heet `sort`, `mean` of `pooled`.
    #
    # Een koppelteken telt als woordteken, anders keurt `.sum()` elke vraag af
    # die "Wilcoxon rank-sum-toets" zegt — en die toets móet bij naam genoemd.
    verraden = sorted(
        term for term in giveaway_terms(draft.reference_answer, draft.setup)
        if len(term) >= 3
        and re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", draft.question, re.IGNORECASE)
    )
    if verraden:
        return herstelbaar(draft, f"de vraag noemt het antwoord: {', '.join(verraden)}")

    result = evaluate(draft.setup, draft.reference_answer, tolerance_for(kind))
    if result.error:
        return herstelbaar(draft, f"referentieantwoord draait niet: {result.error}")
    if result.returns_none and not result.changed_state:
        # Elke andere uitdrukking die None oplevert zou ook goed gerekend
        # worden; zo'n kaart toetst niets.
        return herstelbaar(draft, "referentieantwoord levert niets op en verandert niets")

    if kind == "stats":
        # Zonder uitwerking is een toetskaart alleen een getal, en dan leer je
        # er niets van — dat is juist waar deze soort voor bestaat.
        if not draft.explanation.strip():
            return herstelbaar(draft, "toetskaart zonder uitwerking")
        # Je schrijft op een tentamen één getal op. Een array of een
        # scipy-resultaatobject valt niet in te tikken en niet af te ronden.
        if not result.returns_number:
            return herstelbaar(draft, f"referentieantwoord is geen getal maar {result.value_repr[:60]}")
        if result.matches_fixture:
            return herstelbaar(
                draft,
                f"de uitkomst is gelijk aan '{result.matches_fixture}' uit de opzet; "
                "er valt niets uit te rekenen",
            )

        # De uitwerking is prozawerk van hetzelfde model dat de uitdrukking
        # schreef, en het rekent zich er geregeld in vast: in de eerste echte
        # ronde spraken vier van de negen uitwerkingen het nagekeken getal
        # tegen (2,36 opgeschreven waar 2,223 uitkwam). Een uitwerking die iets
        # anders beweert dan wat je goed gerekend krijgt is erger dan geen
        # uitwerking, dus die gaat weg.
        expected = float(result.number)
        marge = tolerance_for(kind) or 0.0
        if not _agrees(draft.computed_value, expected, marge):
            return herstelbaar(
                draft,
                f"de uitwerking komt uit op {draft.computed_value:g} "
                f"maar de uitdrukking geeft {expected:g}",
            )
        if not any(_agrees(number, expected, marge) for number in numbers_in(draft.explanation)):
            return herstelbaar(draft, f"de uitkomst {expected:g} staat nergens in de uitwerking")
        nagepraat = narrates_the_code(draft.explanation)
        if nagepraat:
            return herstelbaar(draft, f"de uitwerking wijst naar de code ('{nagepraat}') in plaats van af te leiden")
    return None


def generate_cards(
    db: Session,
    *,
    course_slug: str,
    section_path: str,
    count: int = 8,
    kind: str = "code",
    client=None,
    topic: str | None = None,
    week: int | None = None,
    chunks: list[Chunk] | None = None,
) -> GenerationReport:
    spec = KIND_SPECS.get(kind)
    if spec is None and kind not in ("exam", "keuze", "output"):
        raise UnknownKind(f"onbekende kaartsoort '{kind}'")

    # De aanroeper kan de fragmenten zelf kiezen (per week, per onderwerp);
    # anders is het deck de bron, zoals bij het genereren vanaf de sectielijst.
    chunks = chunks if chunks is not None else section_chunks(db, course_slug, section_path)
    if not chunks:
        raise NoSourceMaterial(f"'{section_path}' heeft geen tekst in {course_slug}")

    client = client or answer_client()
    if client is None:
        raise NoSourceMaterial("er is geen antwoordmodel geconfigureerd om kaarten mee te maken")

    if kind == "output":
        # "Wat print dit?" — de sleutel komt van het uitvoeren, niet van het model.
        from app.services.practice.output_generation import generate_output_cards

        report = GenerationReport()
        generate_output_cards(
            db,
            course_slug=course_slug,
            section_path=section_path,
            chunks=chunks,
            count=min(count, MAX_CARDS_PER_CALL),
            client=client,
            report=report,
            topic=topic,
            week=week,
        )
        if report.created:
            db.commit()
        return report

    if kind == "keuze":
        # "Welke toets hoort hier?" — een meerkeuzekaart met een procedure als
        # label, zodat de ronde erop kan afwisselen.
        from app.services.practice.choice_generation import generate_choice_cards

        report = GenerationReport()
        generate_choice_cards(
            db,
            course_slug=course_slug,
            section_path=section_path,
            chunks=chunks,
            count=min(count, MAX_CARDS_PER_CALL),
            client=client,
            report=report,
            topic=topic,
            week=week,
        )
        if report.created:
            db.commit()
        return report

    if kind == "exam":
        # Begripsvragen vallen niet uit te voeren; die hebben hun eigen sloten.
        from app.services.practice.exam_generation import generate_exam_cards

        report = GenerationReport()
        generate_exam_cards(
            db,
            course_slug=course_slug,
            section_path=section_path,
            chunks=chunks,
            count=min(count, MAX_CARDS_PER_CALL),
            client=client,
            report=report,
            topic=topic,
            week=week,
        )
        return report

    by_id = {chunk.id: chunk for chunk in chunks}
    bestaand = [
        question.strip()
        for (question,) in db.execute(
            select(PracticeCard.question).where(
                PracticeCard.course_slug == course_slug,
                PracticeCard.section_path == section_path,
            )
        )
    ]
    seen = {question.lower() for question in bestaand}

    parsed = client.responses.parse(
        model=settings.openai_answer_model,
        instructions=spec.instructions,
        input=_build_prompt(chunks, min(count, MAX_CARDS_PER_CALL), spec.noun, bestaand),
        text_format=spec.batch_model,
    )
    batch = parsed.output_parsed

    report = GenerationReport()

    def store(draft) -> None:
        chunk = by_id[draft.chunk_id]
        card = PracticeCard(
            course_slug=course_slug,
            document_id=chunk.document_id,
            chunk_id=chunk.id,
            section_path=section_path,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            kind=kind,
            setup=draft.setup.strip(),
            question=draft.question.strip(),
            reference_answer=draft.reference_answer.strip(),
            explanation=draft.explanation.strip(),
            # Zonder week valt een kaart buiten het weekoverzicht; zonder
            # onderwerp lijkt elk onderwerp van die week nog leeg.
            week=week if week is not None else None,
            spec={"topic": topic} if topic else {},
        )
        db.add(card)
        seen.add(card.question.lower())
        report.created.append(card)

    def sift(drafts, *, herstelronde: bool) -> list[tuple]:
        """Bewaar wat deugt, meld wat niet deugt, geef terug wat te herstellen is.

        In de herstelronde zelf wordt niets meer verzameld: één ronde is genoeg,
        en anders blijft het model zichzelf corrigeren op onze rekening.
        """
        repairable: list[tuple] | None = None if herstelronde else []
        for draft in drafts:
            reason = _accept(draft, by_id, seen, kind, repairable)
            if not reason:
                store(draft)
            elif herstelronde and reason is DUPLICATE:
                # Het model levert in de herstelronde soms ook de kaarten terug
                # die al goed waren. Dat is geen afkeuring, dus dat meldt niet.
                continue
            else:
                report.rejected.append((draft.question or draft.setup, reason))
        return repairable or []

    te_herstellen = sift(batch.cards, herstelronde=False)

    # Eén herstelronde. Meer niet: als het model met de reden ernaast nog steeds
    # dezelfde fout maakt, is de kaart niet te redden.
    if te_herstellen:
        hersteld = client.responses.parse(
            model=settings.openai_answer_model,
            instructions=REPAIR_INSTRUCTIONS,
            input=_repair_prompt(te_herstellen),
            text_format=spec.batch_model,
        ).output_parsed
        # De afkeuringen van zojuist gaan weg: ze zijn opnieuw beoordeeld.
        report.rejected = [
            item for item in report.rejected
            if item[0] not in {draft.question or draft.setup for draft, _ in te_herstellen}
        ]
        sift(hersteld.cards, herstelronde=True)

    if report.created:
        db.commit()
    return report
