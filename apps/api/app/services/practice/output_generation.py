"""Kaarten "wat print dit?": een fragment uit de stof, en jij voorspelt de uitvoer.

Waarom deze soort er is. Bij college 8 zei de docent van SSO deel 2 dat het
tentamen een codefragment kan laten zien met de vraag wat de uitvoer is — maar
dat je geen syntax uit je hoofd hoeft te schrijven. Dat is een andere
vaardigheid dan code schrijven (de `code`-kaart) of een toets kiezen (de
`keuze`-kaart): code lézen en in je hoofd uitvoeren.

De sleutel komt van de interpreter, niet van het model. Het model stelt een
fragment voor plus wat het dénkt dat eruit komt; het fragment wordt uitgevoerd
(twee keer, om toeval uit te sluiten), en de echte uitvoer is het antwoord.
Denkt het model iets anders dan er uitkomt, dan beschrijft zijn uitleg een
redenering die niet klopt — en die kaart gaat weg.
"""
from __future__ import annotations

import ast
import builtins
import re

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document, PracticeCard
from app.services.practice.exam_generation import DUPLICATE, grounded, squash
from app.services.practice.snippets import SnippetRejected, output_problem, outputs_match, run_snippet_measured
from app.services.terms import KEEP_TERMS


# Een kaart is een hap, geen notebookcel. In SSO week 5 stonden er fragmenten
# van 8 tot 13 regels: dat leest als een programma. Tien regels is precies een
# LP met twee variabelen en twee beperkingen, inclusief import en print.
MAX_SNIPPET_LINES = 10

# Lost een fragment een model op, dan moet je dat op papier kunnen: twee
# variabelen grafisch, drie binaire door de acht mogelijkheden af te lopen. Alle
# twaalf output-kaarten van week 5 lieten een model oplossen, tot een knapsack
# met zes items — en "wat print dit" werd "los dit op in je hoofd".
MAX_SOLVED_VARIABLES = 3


class OutputDraft(BaseModel):
    chunk_id: str = Field(description="Het chunk_id waar het fragment op steunt, letterlijk overgenomen")
    question: str = Field(description="Eén korte zin in het Nederlands, bijvoorbeeld 'Wat print dit fragment?'")
    code: str = Field(description=f"Een zelfstandig Python-fragment van hooguit {MAX_SNIPPET_LINES} regels dat iets print")
    claimed_output: str = Field(description="Wat het fragment volgens jou precies print")
    explanation: str = Field(
        description="Stap voor stap waarom juist dit eruit komt, in het Nederlands; zo dat een student die het fout had ziet waar"
    )
    source_quote: str = Field(description="Letterlijk overgenomen zin uit het materiaal waar dit fragment op steunt")


class OutputBatch(BaseModel):
    cards: list[OutputDraft] = Field(default_factory=list)


INSTRUCTIONS = (
    "Je maakt oefenvragen voor een schriftelijk tentamen. Het tentamen laat een kort "
    "Python-fragment zien en vraagt wat het print. Syntax uit je hoofd schrijven hoeft niet; "
    "code lezen en in je hoofd uitvoeren wel.\n"
    "\n"
    "- Bouw elk fragment op wat er in het aangeboden materiaal staat: dezelfde modellen, "
    "dezelfde bibliotheken (vaak PuLP), dezelfde ideeën. Varieer de getallen of een detail, "
    "zodat het geen overtypen is.\n"
    f"- Het fragment is zelfstandig: alle imports en gegevens staan erin. Hooguit {MAX_SNIPPET_LINES} "
    "regels; korter is beter.\n"
    "- Laat het bij voorkeur iets over het model zelf printen, niet de oplossing: de doelfunctie, "
    "een beperking, de status van een onoplosbaar of onbegrensd model, de waarde van een `lpSum` "
    "voor gegeven getallen, de volgorde van een lus. Lost het fragment toch een model op, dan met "
    f"hooguit {MAX_SOLVED_VARIABLES} variabelen: zo klein dat je het op papier oplost.\n"
    "- Het print iets kort en eenduidigs. Hooguit een paar regels uitvoer.\n"
    "- Niets willekeurigs zonder vaste seed. Laat een solver niets naar het scherm schrijven "
    "(msg=False).\n"
    "- De vraag test begrip: wat doet een beperking, wat verandert integraliteit, welke "
    "iteratie print wat — niet alleen of je Python kunt lezen.\n"
    "- `claimed_output` is precies wat het fragment print.\n"
    f"- De uitleg zegt stap voor stap waarom juist dit eruit komt, in het Nederlands. {KEEP_TERMS}\n"
    "- `source_quote` staat letterlijk in het aangeboden materiaal.\n"
)


_CODE_BLOCK_RE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.DOTALL)
_ATTRIBUTE_RE = re.compile(r"\.([A-Za-z_]\w*)")
_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

# Wat elk Python-fragment gebruikt, en dus niets zegt over de stof: ingebouwde
# functies en de gewone methoden van lijsten, woordenboeken en strings.
_GENERIC_NAMES = frozenset(dir(builtins)) | frozenset(
    {
        "items", "keys", "values", "append", "extend", "get", "pop", "format", "join", "split",
        "strip", "startswith", "endswith", "lower", "upper", "replace", "copy", "update", "sort",
        "index", "count", "add", "remove", "insert", "setdefault", "rstrip", "lstrip", "splitlines",
    }
)


def course_code_names(texts: list[str]) -> set[str]:
    """De namen die de code in de stof gebruikt: `LpProblem`, `lpSum`, `value`…

    Alleen uit codeblokken, en alleen wat een aanroep of attribuut is — een
    `import pulp` alleen zegt nog niets. Ingebouwde functies en gewone
    lijst- en stringmethoden vallen af.
    """
    namen: set[str] = set()
    for text in texts:
        for block in _CODE_BLOCK_RE.findall(text or ""):
            namen.update(_ATTRIBUTE_RE.findall(block))
            namen.update(_CALL_RE.findall(block))
    return {naam for naam in namen if len(naam) > 2 and naam not in _GENERIC_NAMES}


def _snippet_names(code: str) -> set[str]:
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return set()
    namen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            namen.add(node.attr)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            namen.add(node.func.id)
    return namen


def check_output_draft(
    draft: OutputDraft,
    *,
    material: list[str],
    seen: set[str],
    course_names: set[str] | None = None,
) -> tuple[str | None, str]:
    """(reden waarom de kaart niet deugt of None, de echte uitvoer).

    `course_names` zijn de namen uit de code van de stof (`course_code_names`).
    De generator geeft ze altijd mee; None slaat die ene controle over, voor
    tests van de andere regels.
    """
    code = draft.code.strip()
    if squash(code) in seen:
        return DUPLICATE, ""

    # Vóór het draaien: te lang is te lang, wat het ook print. Lege regels tellen
    # niet; die maken een fragment leesbaarder, niet zwaarder.
    regels = sum(1 for line in code.splitlines() if line.strip())
    if regels > MAX_SNIPPET_LINES:
        return f"het fragment is {regels} regels; op een kaart past hooguit {MAX_SNIPPET_LINES}", ""

    # Een codevraag moet over de code van de stof gaan. In de eerste echte ronde
    # kwamen er kaarten over het printen van collegetitels met enumerate: Python
    # lezen, geen optimalisatie. Een instructie hield dat niet tegen; dit wel.
    if course_names is not None:
        if not course_names:
            return "de stof van dit onderwerp bevat geen code, dus een codevraag zou er niet op steunen", ""
        if not (_snippet_names(code) & course_names):
            return "het fragment gebruikt niets uit de code van de stof (geen LpProblem, lpSum, …)", ""
    if not draft.explanation.strip():
        return "er staat geen uitleg bij; daar leer je van als je het fout had", ""
    if not grounded(draft.source_quote, material):
        return "het citaat staat niet letterlijk in de stof", ""

    try:
        uitvoer, groottes = run_snippet_measured(code)
    except SnippetRejected as exc:
        return str(exc), ""

    probleem = output_problem(uitvoer)
    if probleem:
        return probleem, uitvoer

    # De grootte komt van de interpreter, niet uit de code geraden: een
    # `LpVariable.dicts` over een lijst is één regel en zes variabelen.
    if groottes and max(groottes) > MAX_SOLVED_VARIABLES:
        return (
            f"het fragment lost een model met {max(groottes)} variabelen op; "
            f"met de hand te doen is hooguit {MAX_SOLVED_VARIABLES}"
        ), uitvoer

    # De kern: wat het model dacht moet kloppen met wat er uitkomt. Anders legt
    # de uitleg een redenering uit die niet tot deze uitvoer leidt.
    if not outputs_match(uitvoer, draft.claimed_output):
        return f"het model denkt dat er '{draft.claimed_output.strip()[:60]}' uitkomt, maar het is '{uitvoer[:60]}'", uitvoer

    return None, uitvoer


def generate_output_cards(
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
    """Maak "wat print dit?"-kaarten uit deze chunks en zet in `report` wat er gebeurde."""
    from app.core.config import settings

    by_id = {chunk.id: chunk for chunk in chunks}
    material = [squash(chunk.text) for chunk in chunks]
    # Uit de ruwe tekst, niet de gesquashte: daar staan de codeblokken nog in.
    namen = course_code_names([chunk.text for chunk in chunks])
    if not namen:
        # Zonder code in de stof valt er niets te vragen; bespaar de aanroep.
        report.rejected.append((topic or section_path, "de stof van dit onderwerp bevat geen code"))
        return
    seen = {
        squash(setup)
        for (setup,) in db.execute(
            select(PracticeCard.setup).where(PracticeCard.course_slug == course_slug, PracticeCard.kind == "output")
        )
        if setup
    }

    fragments = "\n\n".join(f"[{chunk.id}]\n{chunk.text}" for chunk in chunks)
    onderwerp = f"Het onderwerp van deze ronde is: {topic}.\n\n" if topic else ""
    parsed = client.responses.parse(
        model=settings.openai_answer_model,
        instructions=INSTRUCTIONS,
        input=f"{onderwerp}Maak {count} vragen 'wat print dit fragment?' uit dit materiaal.\n\n{fragments}",
        text_format=OutputBatch,
    )

    for draft in (parsed.output_parsed.cards if parsed.output_parsed else []):
        reden, uitvoer = check_output_draft(draft, material=material, seen=seen, course_names=namen)
        if reden:
            report.rejected.append((draft.question or draft.code[:60], reden))
            continue

        chunk = by_id.get(draft.chunk_id) or chunks[0]
        document = db.get(Document, chunk.document_id)
        card = PracticeCard(
            course_slug=course_slug,
            document_id=chunk.document_id,
            chunk_id=chunk.id,
            section_path=section_path,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            kind="output",
            setup=draft.code.strip(),
            question=draft.question.strip() or "Wat print dit fragment?",
            # De sleutel is wat er echt uitkwam, niet wat het model dacht.
            reference_answer=uitvoer,
            explanation=draft.explanation.strip(),
            week=week if week is not None else (document.week if document else None),
            spec={"topic": topic or "", "source_quote": draft.source_quote.strip(), "generated": True},
        )
        db.add(card)
        seen.add(squash(card.setup))
        report.created.append(card)
