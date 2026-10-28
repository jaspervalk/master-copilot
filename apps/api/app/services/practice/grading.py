"""Tentamenvragen nakijken.

Meerkeuze is mechanisch: de verzameling gekozen letters moet precies de goede
zijn, zoals op het tentamen, waar je bij vierkante vakjes alleen punten krijgt
als je alle goede aankruist en geen foute.

Open vragen kijkt een model na tegen het beoordelingsschema, maar het model
beslist niet alleen. Een punt telt pas als het oordeel een citaat uit jouw
antwoord aanwijst dat daar ook letterlijk staat. Een mild model dat punten
geeft voor iets wat je niet opschreef, valt zo door de mand — en dat is precies
de fout die je in een oefenomgeving het minst kunt gebruiken, want dan denk je
dat je iets kunt wat je niet kunt.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.core.config import settings
from app.models import PracticeCard
from app.services.terms import KEEP_TERMS

try:  # pragma: no cover — de app moet importeerbaar blijven zonder de SDK
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


logger = logging.getLogger(__name__)

LETTERS = "abcdefgh"

# Een open vraag telt als "goed" voor de herhaling vanaf driekwart van de
# punten. Volle punten eisen zou een antwoord dat alleen een bijzin mist
# eindeloos laten terugkomen; de helft zou te veel doorlaten.
OPEN_PASS_RATIO = 0.75

# Kortere citaten zijn te toevallig om iets te bewijzen ("the", "k").
_MIN_EVIDENCE_CHARS = 3


class NoGrader(RuntimeError):
    """Er is geen model om open antwoorden mee na te kijken."""


class InvalidChoice(ValueError):
    """Het antwoord op een meerkeuzevraag is geen geldige keuze."""


@dataclass
class ChoiceResult:
    correct: bool
    selected: list[int]
    expected: list[int]
    score: float
    max_score: float


def parse_letters(answer: str, option_count: int) -> list[int]:
    """`"b, d"`, `"bd"` en `"B D"` zijn allemaal dezelfde keuze."""
    letters = re.findall(r"[a-z]", answer.lower())
    if not letters:
        raise InvalidChoice("kies minstens één optie")
    geldig = LETTERS[:option_count]
    onbekend = sorted({letter for letter in letters if letter not in geldig})
    if onbekend:
        raise InvalidChoice(f"{', '.join(onbekend)} is geen optie; kies uit {', '.join(geldig)}")
    return sorted({geldig.index(letter) for letter in letters})


def grade_choice(card: PracticeCard, answer: str) -> ChoiceResult:
    spec = card.spec or {}
    options = spec.get("options") or []
    expected = sorted(spec.get("answer") or [])
    selected = parse_letters(answer, len(options))
    if not spec.get("multi") and len(selected) != 1:
        raise InvalidChoice("bij deze vraag hoort precies één antwoord")

    correct = selected == expected
    points = card.points or 0.0
    return ChoiceResult(
        correct=correct,
        selected=selected,
        expected=expected,
        score=points if correct else 0.0,
        max_score=points,
    )


# --- open vragen ------------------------------------------------------------


class CriterionVerdict(BaseModel):
    criterion: int = Field(description="Het nummer van het criterium zoals het in het schema staat: 1, 2, ...")
    awarded: float = Field(description="Toegekende punten, tussen 0 en het maximum van dit criterium")
    evidence: str = Field(description="Letterlijk citaat uit het antwoord waarop de punten steunen; leeg bij 0")
    comment: str = Field(description="Eén korte zin in het Nederlands")


class OpenVerdict(BaseModel):
    criteria: list[CriterionVerdict] = Field(default_factory=list)
    feedback: str = Field(description="Twee of drie zinnen in het Nederlands: wat ontbrak voor de volle punten")


@dataclass
class CriterionResult:
    criterion: str
    points: float
    awarded: float
    evidence: str
    comment: str
    # Het model gaf punten met een citaat dat niet in het antwoord staat.
    withdrawn: bool = False


@dataclass
class OpenResult:
    score: float
    max_score: float
    criteria: list[CriterionResult] = field(default_factory=list)
    feedback: str = ""

    @property
    def correct(self) -> bool:
        return self.max_score > 0 and self.score >= OPEN_PASS_RATIO * self.max_score


GRADER_INSTRUCTIONS = (
    "Je bent een strenge maar eerlijke examinator van een schriftelijk tentamen. Je kijkt "
    "één antwoord na tegen het beoordelingsschema.\n"
    "\n"
    "- Beoordeel elk criterium apart: hoeveel punten verdient het antwoord, tussen 0 en het "
    "maximum van dat criterium. Halve punten mogen.\n"
    "- Ken alleen punten toe voor wat er staat, niet voor wat de student vermoedelijk "
    "bedoelde. Vaag of algemeen is niet genoeg: 'the model gets worse' zegt niet "
    "'overfitting', en 'use a better model' noemt geen techniek.\n"
    "- Een andere formulering dan het modelantwoord telt volledig mee als ze het criterium "
    "inhoudelijk dekt. Het modelantwoord is een voorbeeld, geen sjabloon.\n"
    "- Spel- en tikfouten kosten geen punten zolang het begrip ondubbelzinnig is: 'gradient "
    "decent' is gradient descent, 'principle component analysis' is principal component "
    "analysis. Het is een geschreven tentamen, geen spellingtoets. Neem in evidence de "
    "tekst over zoals de student hem schreef, met de fout.\n"
    "- evidence: neem letterlijk het stukje uit het antwoord over waarop je de punten "
    "baseert — exact, niet samengevat, niet vertaald, niet verbeterd. Geef je 0 punten, laat "
    "evidence dan leeg.\n"
    "- Vraagt de vraag om een bepaald aantal items, dan tellen alleen de eerste zoveel die "
    "de student noemt. Een extra item levert nooit punten op, ook niet als het beter is dan "
    "een eerder item.\n"
    "- Een inhoudelijk foute bewering die het criterium tegenspreekt kost de punten van dat "
    "criterium, ook als er elders iets goeds staat.\n"
    "- Het antwoord mag in het Engels of het Nederlands zijn; je beoordeelt de inhoud.\n"
    "- comment: één korte zin in het Nederlands per criterium.\n"
    f"- {KEEP_TERMS}\n"
    "- feedback: twee of drie zinnen in het Nederlands over wat er ontbrak voor de volle "
    "punten, zo concreet dat de student het de volgende keer wél opschrijft. Had het "
    "antwoord alle punten, zeg dan kort wat het sterk maakte."
)


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^0-9a-zà-ÿ]+", " ", text.lower()).split())


def _quoted(evidence: str, answer: str) -> bool:
    citaat = _normalize(evidence)
    return len(citaat) >= _MIN_EVIDENCE_CHARS and citaat in _normalize(answer)


def _grading_prompt(card: PracticeCard, answer: str) -> str:
    spec = card.spec or {}
    lines = [f"Vraag ({card.points:g} punten):", card.question]
    if spec.get("figure"):
        lines += ["", "Bij de vraag hoort deze figuur of code:", spec["figure"]]
    if spec.get("max_items"):
        lines += ["", f"Alleen de eerste {spec['max_items']} items die de student noemt tellen mee."]
    lines += ["", "Beoordelingsschema:"]
    # Vanaf 1: zo telt het model uit zichzelf. Met [0] als eerste nummerde het
    # soms toch vanaf 1, en verdween het oordeel over het eerste criterium.
    for index, item in enumerate(spec.get("rubric") or [], start=1):
        lines.append(f"[{index}] ({item['points']:g} punten) {item['criterion']}")
    lines += [
        "",
        "Modelantwoord (een voorbeeld, niet de enige goede formulering):",
        card.reference_answer,
        "",
        "Antwoord van de student, tussen de markeringen:",
        "<<<",
        answer,
        ">>>",
    ]
    return "\n".join(lines)


def _client():
    if not settings.openai_api_key or OpenAI is None:
        return None
    return OpenAI(api_key=settings.openai_api_key)


def grade_open(card: PracticeCard, answer: str, client=None) -> OpenResult:
    rubric = (card.spec or {}).get("rubric") or []
    max_score = card.points or sum(item["points"] for item in rubric)

    if not answer.strip():
        return OpenResult(
            score=0.0,
            max_score=max_score,
            criteria=[
                CriterionResult(item["criterion"], item["points"], 0.0, "", "Niets ingevuld.")
                for item in rubric
            ],
            feedback="Geen antwoord gegeven.",
        )

    client = client or _client()
    if client is None:
        raise NoGrader("er is geen antwoordmodel geconfigureerd om open antwoorden na te kijken")

    verdict: OpenVerdict = client.responses.parse(
        model=settings.openai_answer_model,
        instructions=GRADER_INSTRUCTIONS,
        input=_grading_prompt(card, answer),
        text_format=OpenVerdict,
    ).output_parsed

    # Het schema telt vanaf 1; een 0 in het oordeel zegt dat het model toch vanaf
    # 0 telde. Een criterium zonder oordeel kost zijn punten, dus een verschoven
    # nummering is geen detail: "PCA" kreeg zo 0 van 4.
    base = 0 if any(item.criterion == 0 for item in verdict.criteria) else 1
    by_index: dict[int, CriterionVerdict] = {}
    for item in verdict.criteria:
        by_index.setdefault(item.criterion - base, item)

    results: list[CriterionResult] = []
    for index, item in enumerate(rubric):
        oordeel = by_index.get(index)
        if oordeel is None:
            results.append(CriterionResult(item["criterion"], item["points"], 0.0, "", "Niet beoordeeld."))
            continue
        awarded = min(max(oordeel.awarded, 0.0), float(item["points"]))
        if awarded > 0 and not _quoted(oordeel.evidence, answer):
            logger.info("Punt ingetrokken bij kaart %s: citaat %r staat niet in het antwoord", card.id, oordeel.evidence)
            results.append(
                CriterionResult(
                    item["criterion"], item["points"], 0.0, oordeel.evidence,
                    "Ingetrokken: het aangehaalde stuk staat niet in je antwoord.", withdrawn=True,
                )
            )
            continue
        results.append(
            CriterionResult(item["criterion"], item["points"], awarded, oordeel.evidence if awarded else "", oordeel.comment)
        )

    return OpenResult(
        score=round(sum(result.awarded for result in results), 2),
        max_score=max_score,
        criteria=results,
        feedback=verdict.feedback.strip(),
    )
