"""Eén oefenronde samenstellen: wat doe je nu, en waarom dat.

De keuzes hier komen uit de literatuur over leren, en ze zijn allemaal
mechanisch — er wordt niets geschat en er komt geen model aan te pas.

* **Fouten eerst.** Een kaart die je vorige keer miste levert de meeste winst
  op (Metcalfe 2017). Hij staat ook al vooraan in de herhaalvolgorde.
* **Herhalen vóór nieuw, maar niet in plaats van.** Het toetseffect is het
  best onderbouwde dat er is (Dunlosky e.a. 2013; Yang e.a. 2021), maar een
  verse stapel van veertig kaarten mag je herhaling niet wegdrukken. Vandaar
  een plafond op het aandeel nieuw.
* **Door elkaar, niet op een rij.** Rohrer e.a. (2020) lieten in een
  gerandomiseerde proef in echte klassen zien dat door elkaar oefenen de
  toetsscore een maand later van 38% naar 61% bracht (d = 0.83). De winst zit
  in het kiezen van de juiste procedure — en precies dat oefen je niet als alle
  t-toetsen achter elkaar staan. Voor een vak waar het tentamen vraagt *welke*
  toets je moet doen, is dit het belangrijkste dat deze ronde doet.

Wat hier bewust níet gebeurt: een eigen planningsalgoritme. Bij één gebruiker,
een paar honderd kaarten en vier weken tijd is de winst van een gefit model
(FSRS, SM-17) verwaarloosbaar naast de vraag welke kaarten er zijn.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PracticeCard, utcnow
from app.services.study.horizon import Exam, next_exam
from app.services.study.mastery import NIEUW, ZWAK, CardState, card_states


# Hoe lang een kaart ongeveer kost. Ruwe schattingen: een toetsopgave reken je
# met de hand uit, een open tentamenvraag schrijf je uit, een meerkeuzevraag
# lees je. Ze bepalen alleen hoeveel er in je tijd past.
# Een fragment lezen en in je hoofd uitvoeren zit tussen een meerkeuzevraag en
# een toets met de hand in.
MINUTES_PER_KIND = {"stats": 3.0, "open": 5.0, "mc": 1.5, "code": 1.5, "output": 2.0}
DEFAULT_MINUTES = 2.0

# Hoeveel van een ronde er vrijgehouden wordt voor nieuwe stof, zolang die er
# is. Het is een ondergrens, geen plafond: herhalen heeft eerste keus op de
# rest, maar een stapel achterstallige herhalingen mag nooit betekenen dat je
# een week niet bijhoudt. Is er niets nieuws, dan gaat alles naar herhalen; is
# er niets te herhalen, dan gaat alles naar nieuw.
NEW_SHARE = 0.3

ZWAK_REDEN = "zwak"
HERHALEN = "herhalen"
NIEUW_REDEN = "nieuw"


@dataclass
class SessionCard:
    card_id: str
    question: str
    kind: str
    reason: str
    week: int | None
    topic: str | None
    procedure: str | None
    section_path: str | None
    minutes: float

    @property
    def tag(self) -> str:
        """Waarop de afwisseling let: liefst de procedure, anders het onderwerp,
        anders de week. Bestaande kaarten dragen nog geen procedure."""
        if self.procedure:
            return f"p:{self.procedure}"
        if self.topic:
            return f"o:{self.topic}"
        if self.week is not None:
            return f"w:{self.week}"
        return f"s:{self.section_path or ''}"


@dataclass
class StudySession:
    course_slug: str
    minutes: int
    cards: list[SessionCard] = field(default_factory=list)
    exam: Exam | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def estimated_minutes(self) -> float:
        return round(sum(card.minutes for card in self.cards), 1)

    @property
    def counts(self) -> dict[str, int]:
        counts = {ZWAK_REDEN: 0, HERHALEN: 0, NIEUW_REDEN: 0}
        for card in self.cards:
            counts[card.reason] += 1
        return counts


def minutes_for(kind: str) -> float:
    return MINUTES_PER_KIND.get(kind, DEFAULT_MINUTES)


def _spread(cards: list[SessionCard]) -> list[SessionCard]:
    """Dezelfde kaarten, maar om beurten uit elke hoek.

    Dit gaat over de *keuze*, niet over de volgorde. Wie strikt op ouderdom
    kiest, pakt vijftien kaarten uit dezelfde stapel — bij SSO waren de dertig
    kaarten van college 1 tot en met 3 het oudst — en dan valt er daarna niets
    meer af te wisselen. Groepeer dus op tag, laat de groep met de oudste kaart
    voorgaan, en neem er om beurten één uit.
    """
    groepen: dict[str, list[SessionCard]] = {}
    for card in cards:
        groepen.setdefault(card.tag, []).append(card)

    volgorde = sorted(groepen.values(), key=lambda groep: cards.index(groep[0]))
    verdeeld: list[SessionCard] = []
    while any(volgorde):
        for groep in volgorde:
            if groep:
                verdeeld.append(groep.pop(0))
    return verdeeld


def _spread_over_weeks(cards: list[SessionCard]) -> list[SessionCard]:
    """Nieuwe kaarten om beurten uit elke week, de nieuwste week eerst.

    Op volgorde van aanmaken kwam je pas bij het college van deze week als
    alles van de weken ervoor op was — en dan loop je achter op precies de stof
    die je wilt bijhouden. Binnen een week gaat het weer om beurten per
    onderwerp (`_spread`), zodat drie kaarten uit week 5 niet drie keer
    dezelfde toets zijn.
    """
    per_week: dict[int | None, list[SessionCard]] = {}
    for card in cards:
        per_week.setdefault(card.week, []).append(card)
    rijen = [
        _spread(per_week[week])
        for week in sorted(per_week, key=lambda week: (week is None, -(week or 0)))
    ]
    verdeeld: list[SessionCard] = []
    while any(rijen):
        for rij in rijen:
            if rij:
                verdeeld.append(rij.pop(0))
    return verdeeld


def _interleave(cards: list[SessionCard]) -> list[SessionCard]:
    """Dezelfde kaarten, maar geen twee met dezelfde tag achter elkaar.

    Gulzig en zonder toeval: loop de rij af en pak steeds de eerste kaart die
    een andere tag heeft dan de vorige. Lukt dat niet — er is er nog maar één
    soort over — dan gewoon de eerste. De volgorde blijft daarmee zo dicht
    mogelijk bij de prioriteit (fouten eerst), en is bij dezelfde invoer
    altijd hetzelfde, zodat je hem kunt testen.
    """
    rest = list(cards)
    volgorde: list[SessionCard] = []
    vorige: str | None = None
    while rest:
        keuze = next((card for card in rest if card.tag != vorige), rest[0])
        rest.remove(keuze)
        volgorde.append(keuze)
        vorige = keuze.tag
    return volgorde


def build_session(
    db: Session,
    course_slug: str,
    *,
    minutes: int = 25,
    now: datetime | None = None,
    week: int | None = None,
) -> StudySession:
    """De ronde voor nu, binnen de tijd die je hebt.

    Met `week` blijft het bij die week. Dat is bewust een uitzondering: door
    elkaar oefenen is de regel, maar vlak nadat een college is geweest wil je
    de nieuwe stof eerst een keer op zichzelf zien.
    """
    now = now or utcnow()
    exam = next_exam(db, course_slug, now=now)
    horizon = exam.days_left if exam else None

    states = card_states(db, course_slug, now=now, horizon_days=horizon)
    session = StudySession(course_slug=course_slug, minutes=minutes, exam=exam)

    if not states:
        session.notes.append("Geen kaarten voor dit vak. Maak ze per week hieronder.")
        return session

    if week is not None:
        states = [state for state in states if state.week == week]
        if not states:
            session.notes.append(f"Geen kaarten voor week {week}.")
            return session

    cards = {
        card.id: card
        for card in db.scalars(
            select(PracticeCard).where(PracticeCard.id.in_([state.card_id for state in states]))
        )
    }

    def maak(state: CardState, reason: str) -> SessionCard:
        card = cards[state.card_id]
        return SessionCard(
            card_id=state.card_id,
            question=card.question,
            kind=state.kind,
            reason=reason,
            week=state.week,
            topic=state.topic,
            procedure=(card.spec or {}).get("procedure") or None,
            section_path=state.section_path,
            minutes=minutes_for(state.kind),
        )

    # Een tentamenkaart die je nog nooit maakte blijft buiten de ronde, net als
    # in de herhaalvolgorde: een geïmporteerd proeftentamen gaat over stof die
    # nog moet komen.
    def speelbaar(state: CardState) -> bool:
        card = cards[state.card_id]
        return card.origin is None or state.attempts > 0

    op_tijd = [state for state in states if state.due_at <= now and speelbaar(state)]
    op_tijd.sort(key=lambda state: (state.due_at, state.card_id))

    # Elke stapel om beurten uit zijn hoeken, zodat er straks iets te wisselen
    # valt; binnen een hoek blijft de prioriteit (wie het langst wacht).
    zwak = _spread([maak(state, ZWAK_REDEN) for state in op_tijd if state.state == ZWAK])
    herhalen = _spread([maak(state, HERHALEN) for state in op_tijd if state.state not in (ZWAK, NIEUW)])
    nieuw = _spread_over_weeks([maak(state, NIEUW_REDEN) for state in op_tijd if state.state == NIEUW])

    budget = float(minutes)
    gekozen: list[SessionCard] = []

    def neem(pool: list[SessionCard], grens: float) -> None:
        nonlocal budget
        genomen: list[SessionCard] = []
        for card in pool:
            if card.minutes > grens or card.minutes > budget:
                continue
            genomen.append(card)
            budget -= card.minutes
            grens -= card.minutes
        for card in genomen:
            pool.remove(card)
        gekozen.extend(genomen)

    # Houd een deel vrij voor nieuwe stof, zodat een achterstand in herhalen je
    # niet laat achterlopen. Daarna krijgt herhalen de rest, en wat dan nog over
    # is gaat alsnog naar de andere stapel — geen minuut blijft ongebruikt.
    gereserveerd = float(minutes) * NEW_SHARE if nieuw else 0.0
    neem(zwak, budget - gereserveerd)
    neem(herhalen, budget - gereserveerd)
    neem(nieuw, budget)
    neem(zwak, budget)
    neem(herhalen, budget)

    session.cards = _interleave(gekozen)

    if not session.cards:
        session.notes.append("Niets aan de beurt en geen nieuwe kaarten. Maak er per week bij.")
    return session
