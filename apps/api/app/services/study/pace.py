"""Haal je het, in de tijd die er nog is?

Van alles wat er over leren te vinden is, is dit het stuk dat over vier weken
het meest uitmaakt — méér dan welk planningsalgoritme ook. De vuistregel uit de
literatuur is simpel: zorg dat élke kaart vóór het tentamen minstens twee keer
op afstand goed is gegaan. Dat is geen gevoel maar een som, en dus hoort de
pagina hem te maken in plaats van hem aan jou over te laten.

Twee dingen die hier bewust in zitten.

De som is **optimistisch**: hij rekent alsof je alles goed hebt. Een fout zet de
reeks terug op nul en kost dus extra beurten. Dat wordt niet verstopt — het
staat in de tekst op de pagina, want een schatting die te rooskleurig is zonder
dat je het weet is erger dan geen schatting.

En de dag van het tentamen telt niet mee als studiedag. Je studeert tot de dag
ervóór; wat je die ochtend nog doet is geen spreiding meer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import utcnow
from app.services.study.horizon import next_exam
from app.services.study.mastery import card_states
from app.services.study.session import minutes_for


# Hoe vaak een kaart goed moet zijn gegaan voordat hij vóór het tentamen als
# "gezien" telt. Twee gespreide successen is de ondergrens die in de
# spreidingsliteratuur steeds terugkomt; drie is comfortabeler maar bij een
# horizon van vier weken zelden haalbaar.
TARGET_SUCCESSES = 2


@dataclass(frozen=True)
class Pace:
    exam_name: str
    days_left: int
    cards: int
    # Hoeveel keer er in totaal nog een kaart goed beantwoord moet worden.
    reviews_needed: int
    # Hoeveel beurten er in de gekozen tijd per dag in passen.
    reviews_possible: int
    minutes: int
    minutes_per_day_needed: int

    @property
    def feasible(self) -> bool:
        return self.reviews_possible >= self.reviews_needed


def pace(db: Session, course_slug: str, *, minutes: int = 25, now: datetime | None = None) -> Pace | None:
    """Wat er nog moet gebeuren, tegen de tijd die er is. None zonder tentamen."""
    now = now or utcnow()
    exam = next_exam(db, course_slug, now=now)
    if exam is None:
        return None

    # De dag van het tentamen zelf is geen studiedag meer.
    days_left = max(0, exam.days_left)

    states = card_states(db, course_slug, now=now, horizon_days=exam.days_left)
    if not states:
        return Pace(
            exam_name=exam.name, days_left=days_left, cards=0, reviews_needed=0,
            reviews_possible=0, minutes=minutes, minutes_per_day_needed=0,
        )

    nodig = sum(max(0, TARGET_SUCCESSES - state.streak) for state in states)

    # Gemiddelde kosten van één beurt, gewogen naar wat er ligt: een toetsopgave
    # met de hand kost meer dan een meerkeuzevraag.
    totaal = sum(minutes_for(state.kind) for state in states)
    per_beurt = totaal / len(states)

    mogelijk = int(days_left * minutes / per_beurt) if per_beurt else 0
    per_dag = int(round(nodig * per_beurt / days_left)) if days_left and nodig else 0

    return Pace(
        exam_name=exam.name,
        days_left=days_left,
        cards=len(states),
        reviews_needed=nodig,
        reviews_possible=mogelijk,
        minutes=minutes,
        minutes_per_day_needed=per_dag,
    )
