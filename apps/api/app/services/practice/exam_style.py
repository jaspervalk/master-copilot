"""Hoe een tentamenvraag eruitziet.

Het proeftentamen van FDS gebruikt een handvol vaste vraagvormen, en een
nieuwe vraag in dezelfde vorm oefent meer dan tien vragen in een willekeurige
vorm: je leert ook wat de nakijker verwacht bij "one advantage and one
limitation" of bij een vraag van 10 punten. De vormen staan hier; de
voorbeelden komen rechtstreeks uit de transcripties in `exams/`, zodat de
generator het echte tentamen ziet en niet een beschrijving ervan.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.practice.exams import LETTERS, ExamBlueprint, load_blueprint, transcription_paths


# Vorm → wat hij vraagt en hoe hij wordt nagekeken. De puntenaantallen zijn die
# van het proeftentamen.
TEMPLATES: dict[str, str] = {
    "definition_mc": (
        "Meerkeuze, 1.5 punt: 'What best defines X' of 'What is true about X'. De afleiders zijn "
        "bijna-goede definities van naburige begrippen (causal in plaats van exploratory, "
        "toetsen in plaats van verkennen) of overdrijvingen ('can only be done by…')."
    ),
    "taxonomy_mc": (
        "Meerkeuze, 1.5 punt: in welke categorie valt deze techniek of dit geval "
        "(pre-/in-/post-processing, post hoc of model-based, global of local, "
        "sequential/diverging/qualitative). Beschrijf een concreet scenario en laat de "
        "student de categorie herkennen; noem de categorie niet in het scenario."
    ),
    "api_keyword_mc": (
        "Meerkeuze, 1.5 punt: welke functie of welk trefwoord ontbreekt of hoort hierbij "
        "(`plt.____(2,1)`, broadcasting, `ax.bar`). Afleiders zijn bestaande namen die net iets "
        "anders doen, of namen die plausibel klinken maar niet bestaan."
    ),
    "metric_compute_mc": (
        "Meerkeuze, 1.5 punt: reken een maat uit een klein, volledig gegeven tabelletje uit "
        "(confusion matrix, balance). Opties zijn breuken. Elke afleider is een ándere echte "
        "maat uit dezelfde tabel (recall waar de false negative rate gevraagd wordt, de "
        "verhouding zonder minimum), zodat alleen wie de definitie kent goed zit."
    ),
    "limitation_mc": (
        "Meerkeuze (één of meer goed), 1.5 punt: welke is een beperking of aanname van X. "
        "Minstens één afleider is een wáre bewering die geen beperking is, of een ware "
        "rekenregel die geen aanname van het model is."
    ),
    "application_mc": (
        "Meerkeuze, 1.5 punt: welk probleem kan met methode X worden opgelost. De afleiders "
        "zijn problemen voor een andere familie (classificatie of regressie waar clustering "
        "gevraagd wordt)."
    ),
    "advantage_limitation": (
        "Open, 4 punten: 'Identify one advantage and one limitation of X.' Schema: 2 punten "
        "voor een geldig voordeel, 2 voor een geldige beperking."
    ),
    "justify_property": (
        "Open, 4 punten: 'Briefly justify why X is (non-)parametric / supervised / …'. Schema: "
        "twee inhoudelijke elementen van 2 punten die samen de eigenschap verantwoorden."
    ),
    "hyperparameter_effect": (
        "Open, 4 punten: 'What are the disadvantages of a very low/high H in X?' Schema: twee "
        "gevolgen van 2 punten (bijvoorbeeld overfitting en hoge variantie)."
    ),
    "technique_for_problem": (
        "Open, 4 punten: een scenario met een probleem, en 'what technique can you consider?' "
        "Het scenario beschrijft het symptoom, niet de naam van de oplossing. Schema: de "
        "techniek noemen, en een concrete vorm of één zin waarom hij helpt."
    ),
    "name_examples": (
        "Open, 4 of 6 punten: 'Give N examples of …' of 'Provide N operations …'. Zet het aantal "
        "in max_items; alleen de eerste N tellen. Schema: één criterium per item."
    ),
    "plot_reading": (
        "Open, 4 punten: een figuur, volledig in woorden en getallen beschreven (in de vraag "
        "zelf), en een vraag over wat hij laat zien of welke keuze eruit volgt. Schema: de "
        "keuze en de rechtvaardiging."
    ),
    "distinguish": (
        "Open, 10 punten: 'Explain what distinguishes X from Y.' Schema van vier criteria: wat "
        "X doet, wat Y doet, het precieze verschil, en waarom dat verschil ertoe doet."
    ),
    "mechanism": (
        "Open, 10 punten: 'Explain how technique T can be used to tackle problem P.' Schema: "
        "wat T is, het concrete middel, waarom het werkt, en hoe het het probleem oplost."
    ),
    "case_study": (
        "Open, 4 punten per deelvraag: een casus uit het materiaal — het doel, wat er misging, "
        "of wat eraan te doen is. Alleen als de casus in het aangeboden materiaal staat."
    ),
}

CHOICE_TEMPLATES = frozenset(name for name in TEMPLATES if name.endswith("_mc"))
OPEN_POINTS = (4.0, 6.0, 10.0)
CHOICE_POINTS = 1.5


@dataclass(frozen=True)
class Scoring:
    """Wat een meerkeuzevraag waard is en welke waarden een open vraag mag hebben.

    Standaard die van het proeftentamen. Het echte tentamen van 2026 telt anders
    (college 13: meerkeuze 1 punt, open 2 tot 6), en die regels komen uit de
    opbouw in `exams/opbouw.yml`; met die van vorig jaar werd elke open vraag
    van 3 punten afgekeurd.
    """

    choice_points: float = CHOICE_POINTS
    open_points: tuple[float, ...] = OPEN_POINTS

    def open_label(self) -> str:
        waarden = [f"{value:g}" for value in sorted(set(self.open_points))]
        return waarden[0] if len(waarden) == 1 else ", ".join(waarden[:-1]) + " of " + waarden[-1]


MOCK_SCORING = Scoring()


@dataclass(frozen=True)
class Style:
    """Hoe een vak zijn tentamenvragen stelt: de inleiding van de instructie en de
    vormen. Leeg betekent die van FDS, waar de generator voor gebouwd is.

    `numeric` zijn de vormen waarvan het modelantwoord getallen bevat die worden
    nagerekend (`checks`): het SSO-tentamen is rekenwerk, en een modelantwoord
    met een verkeerd getal leert je het verkeerde antwoord.
    """

    intro: str = ""
    templates: dict[str, str] | None = None
    numeric: frozenset[str] = frozenset()
    # Vorm → wat minstens één narekening moet gebruiken. Een optimum of een
    # kortste pad reken je na met de solver, niet met je eigen tussenstappen:
    # in de eerste SSO-ronde "controleerde" 3*6 + 5*2 = 28 een ontoelaatbaar punt.
    solvers: dict[str, str] | None = None

    def forms(self) -> dict[str, str]:
        return self.templates or TEMPLATES

    def choice_forms(self) -> frozenset[str]:
        return frozenset(name for name in self.forms() if name.endswith("_mc"))


FDS_STYLE = Style()


def _exemplar(section_title: str, question) -> list[str]:
    lines = [f"[{question.template}] ({section_title}, {question.points:g} p) {question.question.strip()}"]
    if question.figure:
        lines.append(f"  figuur: {' '.join(question.figure.split())}")
    if question.type != "open":
        for index, option in enumerate(question.options):
            mark = "*" if LETTERS[index] in question.answer else " "
            lines.append(f"  {mark} {LETTERS[index]}) {option}")
    else:
        for item in question.rubric:
            lines.append(f"  schema ({item.points:g} p): {' '.join(item.criterion.split())}")
        lines.append(f"  modelantwoord: {' '.join(question.model_answer.split())}")
    return lines


def exam_exemplars(course_slug: str, corpus_root: Path) -> str:
    """De vragen uit de tentamentranscripties van dit vak, als stijlvoorbeeld."""
    blocks: list[str] = []
    for path in transcription_paths(corpus_root / course_slug / "exams"):
        blueprint, problems = load_blueprint(path)
        if blueprint is None or problems:
            continue
        blocks.append(_format_blueprint(blueprint))
    return "\n\n".join(blocks)


def _format_blueprint(blueprint: ExamBlueprint) -> str:
    lines = [f"## {blueprint.title} ({blueprint.total_points:g} punten; * = goed antwoord)"]
    for section, question in blueprint.questions():
        lines += _exemplar(section.title, question)
    return "\n".join(lines)
