"""Uitgewerkte voorbeelden maken per onderwerp van een week.

Waarom dit naast de oefenkaarten staat. Bij stof die je nog niet kent levert
het bestuderen van een uitgewerkte oplossing méér op dan zelf proberen: de
meta-analyse van Barbieri e.a. (2023) over wiskundeonderwijs vindt g = 0.48,
bij gelijke of kortere tijd. Maar het draait om zodra je het kunt — dezelfde
uitleg remt dan (Kalyuga e.a. 2003, d = −0.43 bij wie het al weet). Daarom is
een voorbeeld hier geen kaart die terugkomt, maar iets wat bij een onderwerp
hoort en wegvalt zodra je dat onderwerp beheerst.

Onderaan staat één vraag die niet wordt nagekeken. Dat is geen slordigheid:
het formuleren van het antwoord is zelf het werkzame bestanddeel (Bisra e.a.
2018 vinden g = 0.55 voor zulke prompts), en een nagekeken vraag zou er weer
een toets van maken.

De figuur wordt echt getekend. Wat niet tekent, levert geen figuur op — maar
kost het voorbeeld niet: de uitwerking is de kern.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Chunk, Course, Document, Example
from app.services.practice.exam_generation import grounded, squash
from app.services.practice.figures import FigureRejected, matplotlib_available, render_figure
from app.services.practice.generation import NoSourceMaterial, answer_client
from app.services.practice.practice_exams import covers
from app.services.study.generation import MAX_CHUNKS_PER_TOPIC, MIN_CHUNKS_PER_TOPIC
from app.services.terms import KEEP_TERMS
from app.services.weeks_summary import week_material


MIN_STEPS = 2


class StepDraft(BaseModel):
    label: str = Field(description="Wat er in deze stap gebeurt, in twee of drie woorden")
    body: str = Field(description="De stap zelf, met formules tussen $…$")


class ExampleDraft(BaseModel):
    chunk_id: str = Field(description="Het chunk_id waar het voorbeeld op steunt, letterlijk overgenomen")
    title: str = Field(description="Waar dit voorbeeld over gaat, in een halve regel")
    situation: str = Field(description="Het concrete verhaal met getallen: wat is er gemeten, bij hoeveel eenheden")
    steps: list[StepDraft] = Field(description="De uitwerking, stap voor stap; elke stap één gedachte")
    takeaway: str = Field(description="De regel die je hieruit meeneemt, in één zin")
    prompt: str = Field(description="Eén vraag die de lezer zichzelf stelt na het lezen; eindigt op een vraagteken")
    source_quote: str = Field(description="Letterlijk overgenomen zin uit het materiaal die dit onderbouwt")
    figure_code: str = Field(
        default="",
        description=(
            "Matplotlib-code die het idee tekent, op de klaarstaande `ax`, met `np` en eventueel `stats`. "
            "Geen imports, geen plt. Vul dit in tenzij er echt niets te tekenen valt."
        ),
    )
    figure_caption: str = Field(default="", description="Eén regel onder de figuur: wat je erop ziet")


class ExampleBatch(BaseModel):
    examples: list[ExampleDraft] = Field(default_factory=list)


# Waarvoor de student leert, als course.yml het niet zegt (`study.assessment`).
# Eerst was dat "een schriftelijk tentamen statistiek", het vak waarvoor de
# generator gebouwd is; elk ander vak zonder assessment kreeg dan voorbeelden
# voor de verkeerde toets.
_NEUTRAL_ASSESSMENT = "het tentamen van dit vak"
_INTRO = "Je schrijft uitgewerkte voorbeelden voor een student die zich voorbereidt op {assessment}.\n"

INSTRUCTIONS = (
    _INTRO.format(assessment=_NEUTRAL_ASSESSMENT)
    + "\n"
    "Een voorbeeld is geen samenvatting. Het is één concrete situatie met echte getallen, "
    "helemaal uitgewerkt, zodat de lezer de redenering kan volgen en nadoen.\n"
    "\n"
    "- Begin met de situatie: wat is gemeten, bij hoeveel eenheden, wat wil men weten.\n"
    "- Daarna de stappen. Elke stap één gedachte, met de formule erbij tussen $…$. "
    "Reken door met de getallen uit de situatie; laat tussenuitkomsten zien.\n"
    "- Sluit af met wat je eruit meeneemt, in één zin.\n"
    "- De vraag onderaan laat de lezer zelf iets formuleren ('waarom…', 'wat zou er gebeuren als…'). "
    "Geen vraag waarvan het antwoord al in de stappen staat.\n"
    f"- Schrijf in het Nederlands. {KEEP_TERMS}\n"
    "- `source_quote` staat letterlijk in het aangeboden materiaal.\n"
    "\n"
    "**Teken er een figuur bij.** Bij deze stof is bijna altijd iets te tekenen, en het beeld "
    "blijft hangen waar de formule dat niet doet. Laat `figure_code` alleen leeg als er echt "
    "niets te zien valt.\n"
    "\n"
    "Wat past bij welk soort onderwerp:\n"
    "- een verband: puntenwolk met de geschatte lijn of curve erdoorheen;\n"
    "- modelcontrole: residuen tegen voorspelde waarden, of een QQ-plot;\n"
    "- een toets: de verdeling onder $H_0$ met het verwerpingsgebied gearceerd en de "
    "toetsingsgrootheid als verticale lijn;\n"
    "- een transformatie: dezelfde data links op de oorspronkelijke en rechts op de "
    "getransformeerde schaal, of beide curves over elkaar;\n"
    "- een kansmodel: de kansfunctie of de dichtheid;\n"
    "- groepen: de groepsgemiddelden met hun spreiding;\n"
    "- een tijdreeks: de reeks tegen de tijd, zo dat trend, seizoen of cyclus te zien is;\n"
    "- autocorrelatie: de ACF als staafjes per lag, met de grenzen $\\pm 1.96/\\sqrt{T}$ als "
    "stippellijnen;\n"
    "- een decompositie: de reeks met daaronder de trend en de seizoenscomponent;\n"
    "- een voorspelling: de reeks, daarachter de puntvoorspelling en het voorspellingsinterval "
    "als band.\n"
    "\n"
    "Regels voor de tekencode. Er staat één `ax` klaar en `np`, en `stats` uit scipy. Geen "
    "imports, geen `plt`, geen `subplots`. Gebruik de getallen uit je eigen situatie, of "
    "`np.random.default_rng(0)` als je data nodig hebt. Zet Nederlandse labels op de assen en "
    "een legenda waar het helpt. Houd het bij één idee per figuur.\n"
)


@dataclass
class ExampleReport:
    week: int
    created: int = 0
    topics_done: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    # (titel, reden) — voorbeelden die het zonder figuur moeten doen.
    figure_problems: list[tuple[str, str]] = field(default_factory=list)

    def as_lines(self) -> list[str]:
        lines = [f"week {self.week}: {self.created} voorbeelden erbij"]
        for topic, reason in self.skipped:
            lines.append(f"  overgeslagen — {topic}: {reason}")
        for title, reason in self.figure_problems:
            lines.append(f"  zonder figuur — {title[:50]}: {reason}")
        for title, reason in self.rejected:
            lines.append(f"  afgekeurd — {title[:50]}: {reason}")
        return lines


def check_example_draft(draft: ExampleDraft, *, material: list[str]) -> str | None:
    """De reden waarom dit voorbeeld niet deugt, of None."""
    if not draft.title.strip() or not draft.situation.strip():
        return "er staat geen titel of geen situatie bij"
    if len([step for step in draft.steps if step.body.strip()]) < MIN_STEPS:
        return f"een uitwerking heeft minstens {MIN_STEPS} stappen, geen losse bewering"
    if not draft.takeaway.strip():
        return "er staat niet bij wat je eruit meeneemt"
    if not draft.prompt.strip().endswith("?"):
        return "de afsluiter is geen vraag"
    if material and not grounded(draft.source_quote, material):
        return "het citaat staat niet letterlijk in de stof"
    return None


def instructions_for(db: Session, course_slug: str) -> str:
    """De instructie voor dit vak. Zegt course.yml waarvoor je leert
    (`study.assessment`), dan schrijft het model daarvoor: AFCS heeft geen
    tentamen statistiek maar quizzen over de slides."""
    course = db.get(Course, course_slug)
    assessment = (course.study or {}).get("assessment") if course is not None else None
    if not assessment:
        return INSTRUCTIONS
    return INSTRUCTIONS.replace(
        _INTRO.format(assessment=_NEUTRAL_ASSESSMENT), _INTRO.format(assessment=assessment), 1
    )


def _topics_with_examples(db: Session, course_slug: str, week: int) -> set[str]:
    rows = db.execute(
        select(Example.topic).where(
            Example.course_slug == course_slug,
            Example.week == week,
            Example.disabled.is_(False),
        )
    ).all()
    return {topic for (topic,) in rows if topic}


def make_examples(
    db: Session,
    course_slug: str,
    week: int,
    *,
    client=None,
    count: int = 1,
    figures: bool = True,
    topics: list[str] | None = None,
) -> ExampleReport:
    """Eén uitgewerkt voorbeeld per onderwerp van deze week dat er nog geen heeft."""
    report = ExampleReport(week=week)

    client = client or answer_client()
    if client is None:
        raise NoSourceMaterial("er is geen antwoordmodel geconfigureerd om voorbeelden mee te maken")

    # Zonder uitdunnen: we filteren zelf per onderwerp, en een klein
    # document mag niet wegvallen omdat een boek het budget opmaakt.
    material = week_material(db, course_slug, week, fit=False)
    gevraagd = topics if topics is not None else list(material.scope.topics)
    if not gevraagd:
        report.skipped.append((f"week {week}", "geen onderwerpen in course.yml voor deze week"))
        return report
    if not material.chunks:
        report.skipped.append((f"week {week}", "geen stof van deze week in het corpus"))
        return report

    al_gedaan = _topics_with_examples(db, course_slug, week)
    tekenen = figures and matplotlib_available()
    instructions = instructions_for(db, course_slug)

    for topic in gevraagd:
        if topic in al_gedaan:
            continue

        passend: list[Chunk] = []
        for chunk in material.chunks:
            if len(passend) >= MAX_CHUNKS_PER_TOPIC:
                break
            if covers(chunk.text, topic):
                passend.append(chunk)

        if len(passend) < MIN_CHUNKS_PER_TOPIC:
            report.skipped.append((topic, f"minder dan {MIN_CHUNKS_PER_TOPIC} fragmenten over dit onderwerp"))
            continue

        by_id = {chunk.id: chunk for chunk in passend}
        squashed = [squash(chunk.text) for chunk in passend]
        fragments = "\n\n".join(f"[{chunk.id}]\n{chunk.text}" for chunk in passend)

        parsed = client.responses.parse(
            model=settings.openai_answer_model,
            instructions=instructions,
            input=f"Onderwerp: {topic}.\n\nMaak {count} uitgewerkt(e) voorbeeld(en) uit dit materiaal.\n\n{fragments}",
            text_format=ExampleBatch,
        )

        for draft in (parsed.output_parsed.examples if parsed.output_parsed else []):
            reason = check_example_draft(draft, material=squashed)
            if reason:
                report.rejected.append((draft.title, reason))
                continue

            chunk = by_id.get(draft.chunk_id) or passend[0]
            svg = ""
            if not draft.figure_code.strip():
                # Zichtbaar houden: een voorbeeld zonder figuur is een gemiste kans,
                # geen neutrale uitkomst.
                report.figure_problems.append((draft.title, "er is geen figuur voorgesteld"))
            elif draft.figure_code.strip():
                if not tekenen:
                    report.figure_problems.append((draft.title, "de figuur is niet getekend: geen matplotlib"))
                else:
                    try:
                        svg = render_figure(draft.figure_code)
                    except FigureRejected as exc:
                        report.figure_problems.append((draft.title, f"de figuur tekent niet: {exc}"))

            db.add(
                Example(
                    course_slug=course_slug,
                    week=week,
                    topic=topic,
                    title=draft.title.strip(),
                    situation=draft.situation.strip(),
                    steps=[{"label": step.label.strip(), "body": step.body.strip()} for step in draft.steps],
                    takeaway=draft.takeaway.strip(),
                    prompt=draft.prompt.strip(),
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    source_quote=draft.source_quote.strip(),
                    figure_code=draft.figure_code.strip() if svg else "",
                    figure_svg=svg,
                    figure_caption=draft.figure_caption.strip() if svg else "",
                )
            )
            report.created += 1
            if topic not in report.topics_done:
                report.topics_done.append(topic)

    if report.created:
        db.commit()
    return report


def examples_for(db: Session, course_slug: str, *, week: int | None = None) -> list[Example]:
    stmt = select(Example).where(Example.course_slug == course_slug, Example.disabled.is_(False))
    if week is not None:
        stmt = stmt.where(Example.week == week)
    return list(db.scalars(stmt.order_by(Example.week, Example.topic, Example.created_at)))
