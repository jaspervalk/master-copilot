"""Kaarten maken voor een week, onderwerp voor onderwerp.

Het weekoverzicht wijst de gaten aan: onderwerpen uit `course.yml` waar nog
geen kaart bij hoort. Deze module vult ze, met de stof van die week — de
colleges plus de hoofdstukken uit het leesplan, precies zoals de weekkaart die
ook gebruikt.

Twee regels houden het eerlijk:

* een onderwerp krijgt alleen kaarten als er echt fragmenten over gaan
  (`covers` uit de oefententamens: de onderscheidende woorden moeten er staan).
  Anders komt het onderwerp mét reden terug. Een model dat kaarten moet maken
  over stof die er niet is, gaat de stof invullen;
* een onderwerp dat al kaarten heeft wordt overgeslagen, zodat aanvullen twee
  keer draaien niet twee keer kost.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, PracticeCard
from app.services.practice.decks import MAX_SOURCE_CHARS, SEPARATOR
from app.services.practice.generation import NoSourceMaterial, answer_client, generate_cards
from app.services.practice.practice_exams import covers
from app.services.weeks_summary import week_material


# Minder dan dit en het onderwerp staat er niet echt in; dan liever niets.
MIN_CHUNKS_PER_TOPIC = 2

# Hoeveel fragmenten er hoogstens meegaan per onderwerp. Het tekenbudget van
# een deck is de bovengrens; dit voorkomt dat één onderwerp de hele week opslokt.
MAX_CHUNKS_PER_TOPIC = 30

# Soorten die per onderwerp minder kaarten krijgen dan er gevraagd wordt. Code
# lezen is één vaardigheid naast welk model past en hoe je rekent; toen elke
# soort evenveel kreeg, waren in SSO week 5 twaalf van de twintig kaarten
# "wat print dit".
MAX_CARDS_PER_TOPIC = {"output": 1}


@dataclass
class WeekFillReport:
    week: int
    created: int = 0
    rejected: list[tuple[str, str]] = field(default_factory=list)
    # (onderwerp, reden) — wat er níet gemaakt is en waarom.
    skipped: list[tuple[str, str]] = field(default_factory=list)
    topics_done: list[str] = field(default_factory=list)

    def as_lines(self) -> list[str]:
        lines = [f"week {self.week}: {self.created} kaarten erbij"]
        for topic, reason in self.skipped:
            lines.append(f"  overgeslagen — {topic}: {reason}")
        for label, reason in self.rejected:
            lines.append(f"  afgekeurd — {label[:60]}: {reason}")
        return lines


def _section_for(chunks: list[Chunk]) -> str:
    """Het deck waar de kaarten onder komen te hangen: de wortel die het vaakst
    voorkomt. Zo blijft een kaart terug te vinden in de lijst met secties."""
    wortels = Counter(
        (chunk.section_path or "").split(SEPARATOR)[0] for chunk in chunks if chunk.section_path
    )
    return wortels.most_common(1)[0][0] if wortels else ""


def _made_as(kind: str, spec: dict) -> str:
    """Als welke soort een kaart ooit gemaakt is.

    Nodig omdat twee soorten op `mc` uitkomen: een keuzekaart draagt een
    procedure (daar wisselt de ronde op af), een tentamenvraag niet.
    """
    if kind == "mc":
        return "keuze" if spec.get("procedure") else "exam"
    if kind == "open":
        return "exam"
    return kind


def _topics_with_cards(db: Session, course_slug: str, week: int, *, kind: str) -> set[str]:
    """Onderwerpen van deze week die al kaarten van déze soort hebben.

    Per soort, want welk model past en wat het print zijn twee vaardigheden bij
    hetzelfde onderwerp. Eerst telde elke kaart mee, en kreeg "simulation" na
    de keuzekaarten nooit meer een codevraag.
    """
    rows = db.execute(
        select(PracticeCard.kind, PracticeCard.spec).where(
            PracticeCard.course_slug == course_slug,
            PracticeCard.disabled.is_(False),
            PracticeCard.week == week,
        )
    ).all()
    return {
        (spec or {}).get("topic", "")
        for card_kind, spec in rows
        if _made_as(card_kind, spec or {}) == kind
    } - {""}


def fill_week(
    db: Session,
    course_slug: str,
    week: int,
    *,
    kind: str = "keuze",
    count: int = 4,
    client=None,
    topics: list[str] | None = None,
) -> WeekFillReport:
    """Maak `count` kaarten per onderwerp van deze week dat er nog geen heeft.

    Voor een soort uit `MAX_CARDS_PER_TOPIC` wordt `count` daartoe begrensd.
    """
    report = WeekFillReport(week=week)
    count = min(count, MAX_CARDS_PER_TOPIC.get(kind, count))

    # Eén keer vooraf: zonder model valt er niets te maken, en dat is een
    # instelling die ontbreekt — geen uitkomst per onderwerp.
    client = client or answer_client()
    if client is None:
        raise NoSourceMaterial("er is geen antwoordmodel geconfigureerd om kaarten mee te maken")

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

    al_gedaan = _topics_with_cards(db, course_slug, week, kind=kind)

    for topic in gevraagd:
        if topic in al_gedaan:
            continue

        passend: list[Chunk] = []
        budget = MAX_SOURCE_CHARS
        for chunk in material.chunks:
            if len(passend) >= MAX_CHUNKS_PER_TOPIC or budget <= 0:
                break
            if covers(chunk.text, topic):
                passend.append(chunk)
                budget -= len(chunk.text)

        if len(passend) < MIN_CHUNKS_PER_TOPIC:
            report.skipped.append((topic, f"minder dan {MIN_CHUNKS_PER_TOPIC} fragmenten over dit onderwerp"))
            continue

        try:
            ronde = generate_cards(
                db,
                course_slug=course_slug,
                section_path=_section_for(passend),
                count=count,
                kind=kind,
                client=client,
                topic=topic,
                week=week,
                chunks=passend,
            )
        except NoSourceMaterial as exc:
            report.skipped.append((topic, str(exc)))
            continue

        report.created += len(ronde.created)
        report.rejected.extend(ronde.rejected)
        if ronde.created:
            report.topics_done.append(topic)

    return report
