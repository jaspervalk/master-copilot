"""Keuzekaarten: welke procedure hoort bij dit verhaal, en wat controleer je.

Waarom deze soort er is. Het tentamen van SSO is schriftelijk en vraagt geen
R-code; het vraagt of je bij een beschrijving van een onderzoek de juiste toets
kiest en weet welke aannames daarbij horen. Dat is precies de vaardigheid die
je *niet* traint als je per college oefent: staan alle t-toetsen op een rij,
dan weet je het antwoord al voordat je de vraag leest. Rohrer, Dedrick, Hartwig
en Cheung (2020) maten dat in een gerandomiseerde proef in 54 klassen: door
elkaar oefenen bracht de toets een maand later van 38% naar 61%.

Een keuzekaart is een gewone meerkeuzekaart (`kind="mc"`), zodat het nakijken,
de herhaling en de UI die er al zijn hem meteen aankunnen. Wat hij extra draagt
staat in `spec`: `procedure` (waar de ronde op afwisselt) en `checks` (de
aannames die je moet noemen).

Zoals overal hier beslist niet het model of een kaart deugt, maar een reeks
controles: de uitleg moet dezelfde sleutel noemen, de procedure moet het goede
antwoord zijn, de vraag mag het antwoord niet verklappen, en de kaart moet op
een letterlijk citaat uit je eigen stof rusten.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models import Chunk, Document, PracticeCard
from app.services.practice.exam_generation import (
    DUPLICATE,
    grounded,
    squash,
    stated_letters,
)
from app.services.practice.exams import LETTERS
from app.services.terms import KEEP_TERMS


OPTION_COUNT = 4

# Een keuzekaart telt één punt. Niet omdat het tentamen dat zegt, maar omdat
# `grade_choice` met punten rekent; zonder punt zou elke poging 0 van 0 scoren.
CHOICE_POINTS = 1.0

_WORD_RE = re.compile(r"[a-z]{4,}")

# Hoeveel inhoudswoorden twee vragen mogen delen voordat het dezelfde vraag is.
# Alleen samen met hetzelfde goede antwoord: dezelfde toets bij een ánder
# verhaal is juist wat je wilt oefenen.
_SAME_QUESTION_OVERLAP = 0.6

# Woorden die in elke vraag staan en dus niets zeggen over waar hij over gaat.
_FILLER = {
    "welke", "welk", "past", "hier", "hoort", "onderzoeker", "onderzoek", "beste",
    "best", "procedure", "toets", "gebruiken", "wordt", "worden", "willen", "wil",
    "deze", "erbij", "model", "variabele", "waarnemingen", "situatie",
}


class ChoiceDraft(BaseModel):
    chunk_id: str = Field(description="Het chunk_id waar de vraag op steunt, letterlijk overgenomen")
    question: str = Field(
        description=(
            "Het verhaal: opzet van het onderzoek, meetniveau, steekproefgrootte en wat er gevraagd wordt. "
            "Noem de naam van de toets niet."
        )
    )
    options: list[str] = Field(description="Vier procedures, één goede en drie die plausibel zijn")
    correct: str = Field(description="De letter van het goede antwoord: a, b, c of d")
    procedure: str = Field(description="De naam van de goede procedure, letterlijk gelijk aan die optie")
    checks: list[str] = Field(
        default_factory=list, description="De aannames of voorwaarden die je bij deze toets moet nagaan"
    )
    explanation: str = Field(
        description="Begint met 'Goed: <letter>.' en legt uit waaróm deze toets past en waarom de andere niet"
    )
    source_quote: str = Field(description="Letterlijk overgenomen zin uit het materiaal die dit onderbouwt")


class ChoiceBatch(BaseModel):
    cards: list[ChoiceDraft] = Field(default_factory=list)


INSTRUCTIONS = (
    "Je maakt oefenvragen voor een schriftelijk tentamen statistiek. Het tentamen vraagt geen "
    "R- of Python-code: het vraagt welke procedure bij een situatie hoort en wat je daarbij "
    "moet controleren.\n"
    "\n"
    "Elke vraag beschrijft een concreet onderzoek: wat er gemeten is, bij hoeveel eenheden, "
    "gepaard of niet, welk meetniveau, en wat de onderzoeker wil weten. Daarna vraag je welke "
    "toets of welk model daarbij past.\n"
    "\n"
    "- Vier opties. De drie foute zijn plausibel: toetsen die je zou overwegen, niet onzin. "
    "Een goede afleider verschilt op precies één kenmerk (gepaard tegenover ongepaard, "
    "normaal tegenover verdelingsvrij, twee groepen tegenover meer).\n"
    "- Noem de naam van de goede toets niet in de vraag.\n"
    "- `procedure` is letterlijk de tekst van de goede optie.\n"
    "- `checks`: de aannames die je bij die keuze hoort na te gaan, in het Nederlands.\n"
    "- De uitleg begint met 'Goed: <letter>.' en zegt waarom de andere opties afvallen.\n"
    f"- Schrijf vraag, opties en uitleg in het Nederlands. {KEEP_TERMS}\n"
    "- `source_quote` is een zin die letterlijk in het aangeboden materiaal staat.\n"
)


def _names(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _content_words(text: str) -> set[str]:
    return _names(text) - _FILLER


def _asks_the_same(question: str, procedure: str, earlier: list[tuple[str, str]]) -> str | None:
    """Vraagt deze kaart hetzelfde als een die er al is?

    Alleen als het goede antwoord óók hetzelfde is. Twee verhalen die allebei
    op de Wilcoxon uitkomen zijn goed nieuws — dat is precies herkennen. Twee
    formuleringen van hetzelfde verhaal zijn dat niet.
    """
    woorden = _content_words(question)
    if not woorden:
        return None
    for eerdere_vraag, eerdere_procedure in earlier:
        if squash(eerdere_procedure) != squash(procedure):
            continue
        andere = _content_words(eerdere_vraag)
        if not andere:
            continue
        overlap = len(woorden & andere) / min(len(woorden), len(andere))
        if overlap >= _SAME_QUESTION_OVERLAP:
            return f"vraagt hetzelfde als '{eerdere_vraag[:60]}…'"
    return None


def check_choice_draft(
    draft: ChoiceDraft,
    *,
    material: list[str],
    seen: set[str],
    earlier: list[tuple[str, str]] | None = None,
) -> str | None:
    """De reden waarom deze kaart niet deugt, of None als hij deugt."""
    if draft.question.strip().lower() in seen:
        return DUPLICATE

    if len(draft.options) != OPTION_COUNT:
        return f"een keuzevraag heeft vier opties, niet {len(draft.options)}"
    if len({option.strip().lower() for option in draft.options}) != OPTION_COUNT:
        return "twee opties zijn gelijk"

    letter = draft.correct.strip().lower()
    if letter not in LETTERS[:OPTION_COUNT]:
        return f"'{draft.correct}' is geen letter a tot en met d"
    index = LETTERS.index(letter)
    goed = draft.options[index]

    genoemd = stated_letters(draft.explanation)
    if genoemd is None:
        return "de uitleg begint niet met 'Goed: ' en de letter van het goede antwoord"
    if genoemd != [letter]:
        return f"de uitleg noemt {', '.join(genoemd)} als goed, de sleutel zegt {letter}"

    # De procedure moet hetzelfde antwoord aanwijzen, maar hoeft niet woordelijk
    # gelijk te zijn: het model schreef "generalized additive model met smoothing"
    # waar de optie "GAM (generalized additive model)" heette. Wat telt is dat de
    # een in de ander zit — dan wijst de tag naar dezelfde toets.
    procedure, antwoord = squash(draft.procedure), squash(goed)
    if procedure not in antwoord and antwoord not in procedure:
        return f"de procedure '{draft.procedure}' is niet het goede antwoord '{goed}'"

    # De vraag mag de naam van de goede toets niet dragen. Vergelijken op de
    # inhoudswoorden van die optie: "Wilcoxon signed-rank test" verraadt zich
    # ook als "de signed-rank test".
    woorden = _names(goed)
    if woorden and woorden <= _names(draft.question):
        return f"de vraag noemt het antwoord al ('{goed}')"

    if not [check for check in draft.checks if check.strip()]:
        return "er staat geen controle bij: welke aannames moet je nagaan?"

    if not grounded(draft.source_quote, material):
        return "het citaat staat niet letterlijk in de stof"

    zelfde = _asks_the_same(draft.question, draft.procedure, earlier or [])
    if zelfde:
        return zelfde

    return None


def generate_choice_cards(
    db: Session,
    *,
    course_slug: str,
    section_path: str,
    chunks: list[Chunk],
    count: int,
    client,
    report,
    topic: str | None = None,
    week: int | None = None,
) -> None:
    """Maak keuzekaarten uit deze chunks en zet aan `report` wat er gebeurde."""
    from app.core.config import settings

    by_id = {chunk.id: chunk for chunk in chunks}
    material = [squash(chunk.text) for chunk in chunks]
    bestaand = db.execute(
        PracticeCard.__table__.select()
        .with_only_columns(PracticeCard.question, PracticeCard.spec)
        .where(PracticeCard.course_slug == course_slug, PracticeCard.section_path == section_path)
    ).all()
    seen = {question.strip().lower() for question, _ in bestaand}
    earlier = [
        (question, (spec or {}).get("procedure", ""))
        for question, spec in bestaand
        if (spec or {}).get("procedure")
    ]

    fragments = "\n\n".join(f"[{chunk.id}]\n{chunk.text}" for chunk in chunks)
    onderwerp = f"Het onderwerp van deze ronde is: {topic}.\n\n" if topic else ""
    parsed = client.responses.parse(
        model=settings.openai_answer_model,
        instructions=INSTRUCTIONS,
        input=f"{onderwerp}Maak {count} keuzevragen uit dit materiaal.\n\n{fragments}",
        text_format=ChoiceBatch,
    )

    for draft in (parsed.output_parsed.cards if parsed.output_parsed else []):
        reason = check_choice_draft(draft, material=material, seen=seen, earlier=earlier)
        if reason:
            report.rejected.append((draft.question, reason))
            continue

        chunk = by_id.get(draft.chunk_id) or chunks[0]
        document = db.get(Document, chunk.document_id)
        index = LETTERS.index(draft.correct.strip().lower())
        card = PracticeCard(
            course_slug=course_slug,
            document_id=chunk.document_id,
            chunk_id=chunk.id,
            section_path=section_path,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            kind="mc",
            setup="",
            question=draft.question.strip(),
            reference_answer=draft.procedure.strip(),
            explanation=draft.explanation.strip(),
            points=CHOICE_POINTS,
            # `week` en `topic` maken de kaart vindbaar in het weekoverzicht en
            # laten de ronde erop afwisselen; `procedure` is de fijnste tag.
            week=week if week is not None else (document.week if document else None),
            spec={
                "options": [option.strip() for option in draft.options],
                "multi": False,
                "answer": [index],
                "procedure": draft.procedure.strip(),
                "checks": [check.strip() for check in draft.checks if check.strip()],
                "topic": topic or "",
                "source_quote": draft.source_quote.strip(),
                "generated": True,
            },
        )
        db.add(card)
        seen.add(card.question.lower())
        earlier.append((card.question, card.spec["procedure"]))
        report.created.append(card)
