"""Tentamenvragen maken uit het materiaal van één deck.

Dezelfde discipline als bij de code- en toetskaarten — het model stelt voor,
een mechanische controle beslist — maar met andere sloten, want een
begripsvraag valt niet uit te voeren:

- elke vraag moet steunen op een letterlijk citaat uit het aangeboden
  materiaal, en bij een open vraag elk criterium van het schema apart. Een
  schema dat punten geeft voor iets wat nergens in je stof staat, traint je
  op een antwoord dat de nakijker niet zoekt;
- een rekenvraag levert een uitdrukking mee die op precies de goede optie
  uitkomt, en op geen afleider;
- vorm en punten zijn die van het tentamen: vier opties en 1.5 punt, of een
  open vraag van 4, 6 of 10 punten met een schema dat daarop uitkomt.

Het model krijgt het proeftentamen zelf te zien, met antwoorden en schema's.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Chunk, Course, Document, PracticeCard
from app.services.practice.exam_style import (
    CHOICE_POINTS,
    FDS_STYLE,
    MOCK_SCORING,
    TEMPLATES,
    Scoring,
    Style,
    exam_exemplars,
)
from app.services.practice.exams import LETTERS, as_number
from app.services.practice.generation import _agrees, numbers_in
from app.services.practice.sandbox import HAND_COMPUTATION_RTOL, evaluate
from app.services.terms import KEEP_TERMS


DUPLICATE = "vraag bestaat al in dit deck"

# Korter dan dit bewijst een citaat niets: "the model" staat overal.
_MIN_QUOTE_CHARS = 20
_EXACT = 1e-9

# "Goed: b, d." vooraan de uitleg. Zo is een tegenspraak tussen sleutel en uitleg
# mechanisch te vangen: in de eerste echte ronde markeerde het model a en b als
# goed en schreef het in dezelfde kaart "optie 2 is waar, maar geen beperking" —
# het telde de opties in de ene helft vanaf 0 en in de andere vanaf 1.
_STATED_RE = re.compile(r"^\s*goed\s*:\s*((?:[a-d]\b[\s,&]*(?:en\s+|and\s+)?)+)", re.IGNORECASE)


# Op het tentamen betekent deze zin: meer dan één goed. Bij een vraag met één
# goed antwoord zet hij je op het verkeerde been.
_MARK_ALL_RE = re.compile(r"\b(?:mark|select) all\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z]{5,}")


def _category_grounded(option: str, question: str, material: list[str]) -> bool:
    """Staat de categorie uit een goed antwoord ergens in de stof?

    Een indelingsvraag kan een scenario hebben dat letterlijk in het materiaal
    staat, met een categorie die er niet in voorkomt: random forests als
    "in-processing", de indeling van fairnessmethoden geplakt op bomen. Het
    citaat onderbouwt dan het scenario en niet het antwoord. Minstens één
    kenmerkend woord uit de optie — niet al in de vraag — moet in de stof staan.
    """
    vraag = set(_WORD_RE.findall(question.lower()))
    woorden = [woord for woord in _WORD_RE.findall(option.lower()) if woord not in vraag]
    return any(woord in tekst for woord in woorden for tekst in material)


# Een uitleg is voor de student. Praat hij over het schema, het citaat of "het
# oorspronkelijke criterium", dan heeft het model in een herstelronde zijn eigen
# werk besproken — en dat was de kaart waar ook het schema niet meer klopte.
_META_RE = re.compile(r"\b(rubric|criteri(?:um|a|on)|beoordelingsschema|source_quote|chunk|citaat|quote|original)\b", re.IGNORECASE)

# Fouten die letterlijk in de stof staan. Een citaat kan kloppen terwijl de zin
# zelf fout is: de Python Data Science Handbook schrijft dat `plt.axes` een
# rechthoek `[bottom, left, width, height]` krijgt, en in matplotlib is dat
# `[left, bottom, width, height]`. Dit kwam in twee rondes op een kaart.
KNOWN_ERRATA: dict[str, str] = {
    "bottomleftwidthheight": "matplotlib gebruikt [left, bottom, width, height], niet [bottom, left, …]",
}


def known_erratum(draft: ExamDraft) -> str | None:
    tekst = squash(" ".join([draft.question, *draft.options, draft.model_answer, draft.explanation]))
    return next((uitleg for fout, uitleg in KNOWN_ERRATA.items() if fout in tekst), None)


def explanation_problem(explanation: str) -> str | None:
    """Wat er aan de uitleg mankeert, of None.

    Bewust géén eis dat hij Nederlands is. Het model schrijft hem vaak in het
    Engels als de vraag Engels is, en een herstelronde verandert dat niet; een
    taalcontrole gooide zo in één sectie vijf goede tentamenvragen weg. Een
    Engelse uitleg is leesbaar, een weggegooide vraag is weg.
    """
    meta = _META_RE.search(explanation)
    if meta:
        return f"de uitleg praat over het maakproces ('{meta.group(0)}') in plaats van over de stof"
    return None


# "d is recall", "optie b", "option c", "(a)": een uitspraak over een optie bij letter.
_DISTRACTOR_RE = re.compile(r"(?:\b(?:optie|option)\s+([a-d])\b|\b([a-d])\s+is\b|\(([a-d])\))", re.IGNORECASE)


def stated_letters(explanation: str) -> list[str] | None:
    match = _STATED_RE.match(explanation)
    return sorted(set(re.findall(r"\b[a-d]\b", match.group(1).lower()))) if match else None


class RubricDraft(BaseModel):
    criterion: str = Field(description="Wat het antwoord moet bevatten voor deze punten (Engels)")
    points: float
    source_quote: str = Field(description="Letterlijk overgenomen zin uit het materiaal die dit criterium onderbouwt")


class NumberCheck(BaseModel):
    label: str = Field(description="Welk getal uit het modelantwoord, bijvoorbeeld 'T' of 'minimum costs'")
    setup: str = Field(description="Python met alleen toewijzingen van de gegevens uit de vraag, bijvoorbeeld 'n = 252'")
    expression: str = Field(description="Eén Python-uitdrukking die het getal uitrekent uit de setup")


class ExamDraft(BaseModel):
    chunk_id: str = Field(description="Het chunk_id waar de vraag het meest op steunt, letterlijk overgenomen")
    kind: Literal["mc", "open"]
    template: str = Field(description="Eén van de vormen uit de instructie")
    topic: str
    question: str = Field(description="De vraag, in het Engels")
    options: list[str] = Field(description="Meerkeuze: precies vier opties. Open: leeg")
    correct: list[str] = Field(description="Meerkeuze: de letters van de goede opties (a, b, c, d). Open: leeg")
    multi: bool
    compute: str = Field(description="Alleen als alle opties getallen zijn: Python-uitdrukking voor het goede antwoord")
    points: float
    max_items: int = Field(description="Bij een vraag om N items: N. Anders 0")
    rubric: list[RubricDraft] = Field(description="Open: de criteria, samen precies points. Meerkeuze: leeg")
    model_answer: str = Field(description="Open: het antwoord zoals op het tentamen. Meerkeuze: leeg")
    source_quote: str = Field(description="Letterlijk overgenomen zin uit het materiaal die het goede antwoord onderbouwt")
    explanation: str = Field(
        description="Nederlands. Bij meerkeuze beginnend met 'Goed: <letters>.'; daarna waarom, en de valkuil"
    )
    checks: list[NumberCheck] = Field(
        default_factory=list,
        description="Rekenvraag: per getal in het modelantwoord een narekening. Anders leeg",
    )


class ExamBatch(BaseModel):
    cards: list[ExamDraft] = Field(default_factory=list)


def _templates_block(forms: dict[str, str]) -> str:
    return "\n".join(f"- {name}: {description}" for name, description in forms.items())


_FORMS = "<<VORMEN>>"

# Waarvoor de student leert, als course.yml het niet zegt (`study.assessment`).
# Eerst stond hier het tentamen van FDS, het vak waarvoor de generator gebouwd
# is; elk ander vak zonder assessment kreeg dan vragen voor dat tentamen.
_NEUTRAL_ASSESSMENT = "het tentamen van dit vak"


def _assessment_intro(assessment: str, *, with_exemplars: bool) -> str:
    """De inleiding voor een vak dat zegt waarvoor je leert (`study.assessment`).
    Zonder dit kreeg AFCS de inleiding van FDS, met een proeftentamen 'onderaan'
    dat er niet stond."""
    intro = (
        f"Je maakt oefenvragen voor een student die zich voorbereidt op {assessment}. Maak vragen "
        "over de stof uit het aangeboden materiaal, zoals een docent ze daarover zou stellen: "
        "begrip, het verschil tussen naburige begrippen, en wat een figuur of uitkomst betekent.\n"
    )
    if with_exemplars:
        intro += "Onderaan staan vragen van een eerder tentamen: neem hun vorm over, maar schrijf er geen over.\n"
    return intro


_BODY = (
    "\n"
    "Schrijf de vraag, de opties, het schema en het modelantwoord in het Engels, zoals op het "
    "tentamen. Alleen explanation is Nederlands.\n"
    "\n"
    "Vormen (template):\n"
    f"{_FORMS}\n"
    "\n"
    "Voor elke vraag:\n"
    "- source_quote: een letterlijk overgenomen zin of zinsdeel uit het aangeboden materiaal "
    "die het goede antwoord onderbouwt. Kopieer, parafraseer niet — hij wordt opgezocht.\n"
    "- explanation: twee tot vier zinnen in het Nederlands, ook al zijn vraag en opties Engels. "
    f"{KEEP_TERMS} "
    "Waarom het goede antwoord goed is, en de valkuil: bij meerkeuze waarom de verleidelijkste "
    "afleider fout is, bij een open vraag wat je moet opschrijven voor de volle punten. Bij "
    "meerkeuze begint hij letterlijk met 'Goed: ' en de letters, en noem je opties daarna ook "
    "bij hun letter. Voorbeeld: 'Goed: b. Een random forest trekt per split een willekeurige "
    "deelverzameling predictoren; c beschrijft boosting, dat de bomen na elkaar bouwt.'\n"
    "\n"
    "Meerkeuze (kind mc): precies vier opties en points 1.5. correct bevat de letters van de "
    "goede opties (a, b, c, d). Is er meer dan één goed, zet multi op true en eindig de vraag met "
    "'(Mark all correct answers)'; is er één goed, gebruik die zin dan juist niet. Een "
    "indelingsvraag (taxonomy_mc) alleen als het materiaal zelf die indeling geeft, met de "
    "categorieën zoals ze daar heten. Een rekenvraag (metric_compute_mc) heeft vier getallen als "
    "opties; leg in de uitleg alleen uit hoe je het goede antwoord uitrekent, en zeg niets over de "
    "afleiders bij hun letter. Maak afleiders zoals een goed tentamen dat doet: naburige "
    "begrippen, ware beweringen die geen antwoord op de vraag zijn, andere maten uit dezelfde "
    "tabel. Laat rubric en model_answer leeg en zet max_items op 0. Zijn alle opties getallen, "
    "geef dan in compute een Python-uitdrukking die het goede antwoord uitrekent uit de "
    "gegevens in de vraag, zoals `1 / (1 + 5)`. Die wordt uitgevoerd en moet precies op de "
    "goede optie uitkomen. Anders is compute leeg.\n"
    "\n"
    "Open (kind open): points 4, 6 of 10. Laat options, correct en compute leeg en multi false. "
    "rubric: de criteria waarop punten worden gegeven, in de stijl van de schema's hieronder, "
    "samen precies points. Elk criterium krijgt een eigen source_quote uit het materiaal. Kun "
    "je voor een criterium geen zin in het materiaal aanwijzen, dan hoort het niet in het "
    "schema. model_answer: het antwoord zoals je het op het tentamen opschrijft — beknopt, en "
    "dekkend voor elk criterium. Vraagt de vraag om N items, zet N in max_items, anders 0.\n"
    "\n"
    "Verdeling: ongeveer de helft meerkeuze en de helft open. Draagt het materiaal een "
    "vergelijking of een mechanisme, maak dan minstens één open vraag van 10 punten. Varieer "
    "de vormen. Verzin niets wat niet in het materiaal staat.\n"
)

INSTRUCTIONS = _assessment_intro(_NEUTRAL_ASSESSMENT, with_exemplars=False) + _BODY.replace(_FORMS, _templates_block(TEMPLATES))


def _checks_note(style: Style) -> str:
    """Hoe een rekenvraag zijn getallen laat narekenen."""
    if not style.numeric:
        return ""
    vormen = ", ".join(sorted(style.numeric))
    return (
        f"\nRekenvragen (vormen: {vormen}): het modelantwoord rekent het voor, met de getallen. Geef in "
        "checks voor elk uitgerekend getal uit het modelantwoord een narekening: label (welk getal), "
        "setup (alleen toewijzingen van de gegevens uit de vraag, zoals 'n = 252') en expression (één "
        "Python-uitdrukking die het getal uitrekent). Beschikbaar: np, stats (scipy.stats), optimize "
        "(scipy.optimize: linprog, milp), csgraph (scipy.sparse.csgraph: dijkstra, maximum_flow), sparse "
        "en math. Een optimum reken je na met optimize, een kortste pad of maximale stroom met "
        "csgraph: niet met je eigen tussenstappen. Elke narekening wordt uitgevoerd en het getal moet "
        "in het modelantwoord staan "
        "(afgerond op twee of drie decimalen mag). Klopt je eigen getal niet, verbeter dan het "
        "modelantwoord, niet de narekening.\n"
        "Voorbeelden van checks:\n"
        "- toets: setup 'n = 252\\nx = 215\\np0 = 0.9', expression '(x / n - p0) / np.sqrt(p0 * (1 - p0) / n)'\n"
        "- LP (min 2x + 4y, x + 1.5y >= 6, x + 3y >= 9): setup '', expression "
        "'optimize.linprog([2, 4], A_ub=[[-1, -1.5], [-1, -3]], b_ub=[-6, -9]).fun'. Een >=-restrictie "
        "wordt <= door beide kanten met -1 te vermenigvuldigen; maximaliseren is -c minimaliseren, en dan "
        "staat de optimale waarde als -(...).fun in de expression.\n"
        "- ILP: 'optimize.milp(c, constraints=optimize.LinearConstraint(A, lb, ub), integrality=[1, 1], "
        "bounds=optimize.Bounds(0, 1)).fun'\n"
        "- kortste pad: setup 'w = np.array([[0, 6, 4], [0, 0, 1], [0, 0, 0]])' (0 = geen pijl), expression "
        "'csgraph.dijkstra(w, indices=0)[2]'; maximale stroom: "
        "'csgraph.maximum_flow(sparse.csr_matrix(cap), 0, 3).flow_value' met een gehele capaciteitsmatrix cap.\n"
    )


REPAIR_INSTRUCTIONS = (
    "De vragen hieronder zijn afgekeurd; bij elke staat waarom. Verbeter ze en lever ze in "
    "hetzelfde formaat terug, met dezelfde chunk_id.\n"
    "\n"
    "- Een source_quote moet letterlijk in het materiaal staan. Kopieer een zin uit het "
    "materiaal hieronder en verander geen woord. Is er voor een criterium geen onderbouwing "
    "te vinden, haal het criterium dan weg en verdeel de punten over de overige.\n"
    "- Een rekenvraag moet op precies de goede optie uitkomen. Reken compute na en pas de "
    "opties of het goede antwoord aan.\n"
    "- Meerkeuze heeft vier opties en 1.5 punt. Een open vraag is 4, 6 of 10 punten, en het "
    "schema telt daar precies op uit.\n"
    "- De uitleg is Nederlands en gaat over de stof, voor de student: niet over het schema, het "
    "citaat of wat er aan de vraag veranderd is. "
    f"{KEEP_TERMS}"
)


def _scoring_note(scoring: Scoring) -> str:
    """De punten van dit jaar, als ze afwijken van het proeftentamen.

    De vormen en het proeftentamen hieronder noemen nog 1.5 punt en 4, 6 of 10;
    die blijven het voorbeeld voor de vorm, en dit zegt welke punten gelden.
    """
    if scoring == MOCK_SCORING:
        return ""
    return (
        f"\nDe punten van dit jaar: een meerkeuzevraag is {scoring.choice_points:g} punt (niet 1.5), "
        f"een open vraag {scoring.open_label()} punten (niet 4, 6 of 10). De puntenaantallen bij de "
        "vormen hierboven en in het proeftentamen hieronder zijn die van vorig jaar: neem hun vorm "
        "over, maar geef elke vraag de punten van zijn plek en laat het schema daar precies op "
        "uitkomen. Een vraag die vorig jaar 10 punten had, wordt dus kleiner.\n"
    )


def repair_instructions(scoring: Scoring = MOCK_SCORING) -> str:
    return REPAIR_INSTRUCTIONS.replace(
        "Meerkeuze heeft vier opties en 1.5 punt. Een open vraag is 4, 6 of 10 punten",
        f"Meerkeuze heeft vier opties en {scoring.choice_points:g} punt. Een open vraag is "
        f"{scoring.open_label()} punten",
    )


def exam_instructions(
    course_slug: str, scoring: Scoring = MOCK_SCORING, style: Style = FDS_STYLE, assessment: str | None = None
) -> str:
    """De instructie met het proeftentamen van dit vak eronder, als dat er is.

    De inleiding en de vormen komen uit de stijl van het vak; zonder stijl uit
    `assessment` (waarvoor je leert, uit course.yml), en anders een neutrale.
    """
    voorbeelden = exam_exemplars(course_slug, settings.corpus_dir)
    if style.intro.strip():
        inleiding = style.intro.strip() + "\n"
    else:
        inleiding = _assessment_intro(assessment or _NEUTRAL_ASSESSMENT, with_exemplars=bool(voorbeelden))
    romp = _BODY.replace(_FORMS, _templates_block(style.forms()))
    return (
        inleiding + romp + _checks_note(style) + _scoring_note(scoring)
        + ("\nHet proeftentamen:\n" + voorbeelden if voorbeelden else "")
    )


def squash(text: str) -> str:
    """Alleen letters en cijfers. PDF-tekst breekt woorden af ("classi- fication")
    en zet spaties waar ze niet horen; een letterlijk citaat moet daar
    doorheen gevonden worden. NFKC eerst: anders valt een ligatuur (ﬁ, ﬂ) weg
    en wordt "inﬂuenced" "inuenced"."""
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", text).lower())


def source_chunk(draft: ExamDraft, by_id: dict[str, Chunk]) -> Chunk | None:
    """Het fragment waar het citaat echt in staat.

    Het model noemt een chunk_id en citeert soms uit een ander fragment: in de
    eerste oefententamenronde stond een ISLR-zin als "Lecture1, p. 21". Het
    citaat is nagelopen, dus dat bepaalt de vindplaats, niet het genoemde id.
    """
    citaat = squash(draft.source_quote)
    genoemd = by_id.get(draft.chunk_id)
    if genoemd is not None and citaat and citaat in squash(genoemd.text):
        return genoemd
    return next((chunk for chunk in by_id.values() if citaat and citaat in squash(chunk.text)), genoemd)


def grounded(quote: str, material: list[str]) -> bool:
    citaat = squash(quote)
    return len(citaat) >= _MIN_QUOTE_CHARS and any(citaat in tekst for tekst in material)


def _check_choice(draft: ExamDraft, material: list[str], style: Style = FDS_STYLE) -> str | None:
    if draft.template not in style.choice_forms():
        return f"vorm '{draft.template}' hoort niet bij een meerkeuzevraag"
    if len(draft.options) != 4:
        return f"een meerkeuzevraag heeft vier opties, niet {len(draft.options)}"
    if len({option.strip().lower() for option in draft.options}) != 4:
        return "twee opties zijn gelijk"
    goed = sorted({letter.strip().lower() for letter in draft.correct})
    if not goed or any(letter not in LETTERS[:4] for letter in goed):
        return f"de goede opties {draft.correct} zijn geen letters a tot en met d"
    if len(goed) != len(draft.correct):
        return "een goede optie staat dubbel"
    if not draft.multi and len(goed) != 1:
        return "multi is false, maar er zijn meerdere goede opties"
    zegt_alle = bool(_MARK_ALL_RE.search(draft.question))
    if zegt_alle and not draft.multi:
        return "de vraag zegt 'mark all correct answers', maar er is maar één goed antwoord"
    if draft.multi and not zegt_alle:
        return "er zijn meerdere goede antwoorden, maar de vraag zegt niet 'Mark all correct answers'"
    genoemd = stated_letters(draft.explanation)
    if genoemd is None:
        return "de uitleg begint niet met 'Goed: ' en de letters van de goede opties"
    if genoemd != goed:
        return f"de uitleg noemt {', '.join(genoemd)} als goed, maar correct is {', '.join(goed)}"

    numeriek = all(as_number(option) is not None for option in draft.options)
    if draft.template == "metric_compute_mc" and not numeriek:
        return "een rekenvraag heeft vier getallen als opties, zodat het antwoord na te rekenen is"
    if draft.template == "metric_compute_mc":
        # "De som is 12; wat is de within-cluster variation? → 12" is geen
        # rekenvraag, en `compute: 12` rekent niets na.
        if as_number(draft.compute.strip()) is not None:
            return "compute is een kaal getal; een rekenvraag rekent iets uit de gegevens in de vraag uit"
        # De afleiders in een uitleg worden niet nagerekend. In de eerste ronde
        # stond er "d is recall" terwijl recall optie b was.
        genoemd = sorted(
            {letter.lower() for groep in _DISTRACTOR_RE.findall(draft.explanation) for letter in groep if letter} - set(goed)
        )
        if genoemd:
            return (
                f"de uitleg zegt iets over afleider {', '.join(genoemd)}, en dat wordt niet nagerekend; "
                "leg alleen uit hoe je het goede antwoord uitrekent"
            )
    if draft.template == "taxonomy_mc":
        for letter in goed:
            if not _category_grounded(draft.options[LETTERS.index(letter)], draft.question, material):
                return f"de categorie in optie {letter} komt nergens in het materiaal voor"

    if numeriek:
        if not draft.compute.strip():
            return "alle opties zijn getallen, maar compute ontbreekt"
        result = evaluate("", draft.compute)
        if result.error or result.number is None:
            return f"compute levert geen getal op: {result.error or result.value_repr}"
        treffers = [
            LETTERS[index] for index, option in enumerate(draft.options)
            if abs(float(as_number(option)) - result.number) <= _EXACT * max(1.0, abs(result.number))
        ]
        if treffers != goed:
            gevonden = ", ".join(treffers) or "geen optie"
            return f"compute geeft {result.number:.6g}; dat is {gevonden}, maar als goed staat {', '.join(goed)}"
    return None


def _check_open(
    draft: ExamDraft, material: list[str], scoring: Scoring = MOCK_SCORING, style: Style = FDS_STYLE
) -> str | None:
    if draft.template in style.choice_forms() or draft.template not in style.forms():
        return f"vorm '{draft.template}' hoort niet bij een open vraag"
    if draft.points not in scoring.open_points:
        return f"een open vraag is {scoring.open_label()} punten, niet {draft.points:g}"
    if not draft.rubric:
        return "open vraag zonder beoordelingsschema"
    totaal = sum(item.points for item in draft.rubric)
    if abs(totaal - draft.points) > _EXACT or any(item.points <= 0 for item in draft.rubric):
        return f"het schema telt op tot {totaal:g}, de vraag is {draft.points:g} punten"
    # Bij een rekenvraag rekent de sandbox de getallen na, en dat is strenger dan
    # een citaat: "het optimum is (3.6, 2.8)" staat nooit letterlijk in de
    # aantekeningen, en zo vielen alle grafische LP's van SSO af.
    for index, item in enumerate(draft.rubric, start=1):
        if draft.template not in style.numeric and not grounded(item.source_quote, material):
            return f"criterium {index} ('{item.criterion[:50]}'): het citaat staat niet letterlijk in het materiaal"
    if not draft.model_answer.strip():
        return "open vraag zonder modelantwoord"
    if draft.template == "name_examples" and draft.max_items < 1:
        return "een vraag om N items heeft max_items nodig"
    return None


def accept_exam_draft(
    draft: ExamDraft,
    by_id: dict[str, Chunk],
    seen: set[str],
    repairable: list[tuple] | None = None,
    scoring: Scoring = MOCK_SCORING,
    style: Style = FDS_STYLE,
) -> str | None:
    """De reden van afkeuring, of None als de vraag deugt."""

    def herstelbaar(reden: str) -> str:
        if repairable is not None:
            repairable.append((draft, reden))
        return reden

    material = [squash(chunk.text) for chunk in by_id.values()]
    # Een verkeerd chunk_id met een citaat dat wél in het materiaal staat is een
    # verkeerde verwijzing, geen verzonnen vraag: de vindplaats volgt dan het
    # citaat (`source_chunk`).
    if draft.chunk_id not in by_id and not grounded(draft.source_quote, material):
        return "verwijst naar een fragment dat niet is aangeboden"
    if not draft.question.strip():
        return herstelbaar("de vraag is leeg")
    if draft.question.strip().lower() in seen:
        return DUPLICATE
    if not draft.explanation.strip():
        return herstelbaar("geen uitleg")
    probleem = explanation_problem(draft.explanation)
    if probleem:
        return herstelbaar(probleem)
    fout = known_erratum(draft)
    if fout:
        return herstelbaar(f"neemt een bekende fout uit de stof over: {fout}")

    if not grounded(draft.source_quote, material):
        return herstelbaar("de source_quote staat niet letterlijk in het materiaal")

    if draft.kind == "mc":
        reden = _check_choice(draft, material, style)
    else:
        reden = _check_open(draft, material, scoring, style) or (
            _check_numbers(draft, (style.solvers or {}).get(draft.template)) if draft.template in style.numeric else None
        )
    return herstelbaar(reden) if reden else None


def _check_numbers(draft: ExamDraft, solver: str | None = None) -> str | None:
    """Elk getal van een rekenvraag nagerekend, en terug te vinden in het
    modelantwoord. Dezelfde marge als bij een toetskaart: je rekent met de hand
    en rondt af. Heeft de vorm een solver, dan moet een narekening die
    gebruiken: anders rekent hij alleen het eigen rekenwerk over."""
    if not draft.checks:
        return "een rekenvraag zonder narekening: geef in checks per getal uit het modelantwoord een uitdrukking"
    if solver and not any(solver in check.expression for check in draft.checks):
        return f"reken het antwoord na met {solver}… in plaats van met je eigen getallen"
    genoemd = numbers_in(draft.model_answer)
    for check in draft.checks:
        result = evaluate(check.setup, check.expression)
        if result.error or not result.returns_number or result.number is None:
            return f"narekening '{check.label}' levert geen getal op ({(result.error or result.value_repr)[:80]})"
        uitkomst = float(result.number)
        if not math.isfinite(uitkomst):
            return f"narekening '{check.label}' levert geen eindig getal op"
        if not any(_agrees(number, uitkomst, HAND_COMPUTATION_RTOL) for number in genoemd):
            return (
                f"narekening '{check.label}' geeft {round(uitkomst, 3):g}, maar dat getal staat niet in het "
                "modelantwoord"
            )
    return None


def build_card(
    draft: ExamDraft,
    chunk: Chunk,
    document: Document | None,
    course_slug: str,
    section_path: str,
    *,
    topic: str | None = None,
    week: int | None = None,
    choice_points: float = CHOICE_POINTS,
) -> PracticeCard:
    """`topic` en `week` winnen van wat het model en het document zeggen.

    Wie vragen maakt vóór één onderwerp van één week, weet dat beter dan het
    model — en zonder die vastlegging sluit het gat in het weekoverzicht nooit.
    """
    spec: dict = {
        "template": draft.template,
        "topic": (topic or draft.topic).strip(),
        "source_quote": draft.source_quote.strip(),
        "material": f"{document.title}, p. {chunk.page_start}" if document else "",
        "generated": True,
    }
    if draft.kind == "mc":
        goed = sorted({letter.strip().lower() for letter in draft.correct})
        spec |= {
            "options": [option.strip() for option in draft.options],
            "multi": draft.multi,
            "answer": [LETTERS.index(letter) for letter in goed],
            "compute": draft.compute.strip() or None,
        }
        reference = ", ".join(goed)
        points = choice_points
    else:
        spec |= {
            "rubric": [item.model_dump() for item in draft.rubric],
            "max_items": draft.max_items or None,
        }
        reference = draft.model_answer.strip()
        points = draft.points

    return PracticeCard(
        course_slug=course_slug,
        document_id=chunk.document_id,
        chunk_id=chunk.id,
        section_path=section_path,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        kind=draft.kind,
        setup="",
        question=draft.question.strip(),
        reference_answer=reference,
        explanation=draft.explanation.strip(),
        spec=spec,
        points=points,
        week=week if week is not None else (document.week if document else None),
    )


def material_block(chunks: list[Chunk]) -> str:
    return "\n".join(f"\nchunk_id={chunk.id}\n{chunk.text}" for chunk in chunks)


def generate_exam_cards(
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
    """Vul `report` met tentamenvragen uit `chunks`; één herstelronde voor wat afvalt."""
    by_id = {chunk.id: chunk for chunk in chunks}
    documents = {
        document.id: document
        for document in db.scalars(select(Document).where(Document.id.in_({chunk.document_id for chunk in chunks})))
    }
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

    course = db.get(Course, course_slug)
    instructions = exam_instructions(course_slug, assessment=(course.study or {}).get("assessment") if course else None)

    lines = [f"Maak {count} tentamenvragen uit dit materiaal.", ""]
    if bestaand:
        lines += ["Deze vragen staan al in dit deck; maak andere:"] + [f"- {vraag}" for vraag in bestaand] + [""]
    lines += ["Materiaal:", material_block(chunks)]

    batch: ExamBatch = client.responses.parse(
        model=settings.openai_answer_model,
        instructions=instructions,
        input="\n".join(lines),
        text_format=ExamBatch,
    ).output_parsed

    def sift(drafts: list[ExamDraft], *, herstelronde: bool) -> list[tuple]:
        repairable: list[tuple] | None = None if herstelronde else []
        for draft in drafts:
            reden = accept_exam_draft(draft, by_id, seen, repairable)
            if reden is None:
                chunk = source_chunk(draft, by_id)
                card = build_card(draft, chunk, documents.get(chunk.document_id), course_slug, section_path, topic=topic, week=week)
                db.add(card)
                seen.add(card.question.lower())
                report.created.append(card)
            elif herstelronde and reden == DUPLICATE:
                continue
            else:
                report.rejected.append((draft.question, reden))
        return repairable or []

    te_herstellen = sift(batch.cards, herstelronde=False)
    if te_herstellen:
        prompt = ["Verbeter deze vragen.", ""]
        for index, (draft, reden) in enumerate(te_herstellen, start=1):
            prompt += [f"--- vraag {index}", f"afgekeurd omdat: {reden}", draft.model_dump_json(indent=1), ""]
        # Het materiaal gaat opnieuw mee: een citaat repareren kan alleen met
        # de tekst ernaast.
        prompt += ["Materiaal:", material_block(chunks)]
        hersteld: ExamBatch = client.responses.parse(
            model=settings.openai_answer_model,
            instructions=REPAIR_INSTRUCTIONS,
            input="\n".join(prompt),
            text_format=ExamBatch,
        ).output_parsed
        herkansing = {draft.question for draft, _ in te_herstellen}
        report.rejected = [item for item in report.rejected if item[0] not in herkansing]
        sift(hersteld.cards, herstelronde=True)
        # Levert het model minder terug dan er te herstellen was, dan houden de
        # ontbrekende hun oorspronkelijke reden. Anders meldt het rapport "niets
        # afgekeurd" terwijl er vragen zijn verdwenen.
        for draft, reden in te_herstellen[len(hersteld.cards):]:
            report.rejected.append((draft.question, reden))

    if report.created:
        db.commit()

