"""Wanneer een kaart terugkomt.

Afgeleid uit de pogingen, niet apart bijgehouden. `practice_attempts` legt al
vast wat er gebeurde; een tweede administratie ernaast kan uit de pas lopen met
de eerste, en dat is precies het soort stille fout waar je pas achter komt als
je er al een week op hebt vertrouwd. Bijkomend voordeel: alles wat je vóór deze
functie hebt geoefend telt met terugwerkende kracht mee.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PracticeAttempt, PracticeCard, utcnow


# Een ladder à la Leitner. Goed doorschuiven, fout terug naar het begin.
#
# Bewust niet SM-2: dat rekent met een ease factor die je voedt met een oordeel
# in vijf gradaties ("makkelijk", "aarzelend", …). Dat oordeel hebben we niet —
# de interpreter zegt goed of fout, en meer wil je er ook niet bij typen.
INTERVALS_DAYS = (1, 3, 7, 16, 35)

# Het aandeel van de tijd tot het tentamen dat een kaart hoogstens wegblijft.
# Cepeda e.a. (2008) maten dat de beste tussenpoos meebeweegt met hoe lang je
# het moet onthouden: een tiende tot een vijfde daarvan. De bovenkant, anders
# vraagt de planning meer herhalingen dan er dagen zijn.
HORIZON_SHARE = 0.2


@dataclass(frozen=True)
class DueCard:
    card: PracticeCard
    # Sinds wanneer hij klaarstaat. Voor een kaart die je nooit deed is dat het
    # moment waarop hij is gemaakt, zodat oud en nieuw op één regel te sorteren
    # zijn: wie het langst wacht, komt eerst.
    due_at: datetime
    streak: int
    attempts: int

    @property
    def lapsed(self) -> bool:
        """Vorige keer fout. Een kaart die je nog nooit deed telt niet mee."""
        return self.attempts > 0 and self.streak == 0


def interval_for(streak: int, *, horizon_days: int | None = None) -> timedelta:
    """Hoe lang een kaart wegblijft na een reeks van `streak` goede pogingen.

    `horizon_days` is het aantal dagen tot je tentamen. De ladder hierboven is
    gemaakt om iets jarenlang te onthouden; met een datum in zicht is de beste
    tussenpoos een fractie van de tijd die je het nog moet weten (Cepeda e.a.,
    2008). Zonder horizon verandert er niets.
    """
    if streak <= 0:
        # Fout gehad: hij hoort in de eerstvolgende ronde weer langs te komen.
        return timedelta(0)

    dagen = INTERVALS_DAYS[min(streak, len(INTERVALS_DAYS)) - 1]
    if horizon_days is not None and horizon_days > 0:
        # Minstens één dag: een kaart die je vandaag goed had hoeft niet nog
        # een keer vandaag, ook niet de dag voor het tentamen.
        dagen = min(dagen, max(1, int(horizon_days * HORIZON_SHARE)))
    return timedelta(days=dagen)


def _history(db: Session, card_ids: list[str]) -> dict[str, tuple[datetime, int, int]]:
    """Per kaart: het moment van de laatste poging, de reeks goede pogingen
    daarvóór meegerekend, en hoe vaak je hem in totaal deed."""
    if not card_ids:
        return {}

    rows = db.execute(
        select(PracticeAttempt.card_id, PracticeAttempt.correct, PracticeAttempt.created_at)
        .where(PracticeAttempt.card_id.in_(card_ids))
        .order_by(PracticeAttempt.card_id, PracticeAttempt.created_at)
    ).all()

    history: dict[str, tuple[datetime, int, int]] = {}
    for card_id, correct, moment in rows:
        _last, streak, total = history.get(card_id, (moment, 0, 0))
        # De reeks loopt tot de laatste poging: één fout zet hem op nul, ook al
        # ging het daarvóór tien keer goed.
        history[card_id] = (moment, streak + 1 if correct else 0, total + 1)
    return history


def due_cards(
    db: Session,
    course_slug: str,
    *,
    now: datetime | None = None,
    section_path: str | None = None,
    horizon_days: int | None = None,
) -> list[DueCard]:
    """De kaarten die nu klaarstaan, degene die het langst wacht eerst."""
    now = now or utcnow()

    stmt = select(PracticeCard).where(
        PracticeCard.course_slug == course_slug,
        PracticeCard.disabled.is_(False),
    )
    if section_path is not None:
        stmt = stmt.where(PracticeCard.section_path == section_path)
    cards = list(db.scalars(stmt))

    history = _history(db, [card.id for card in cards])

    due: list[DueCard] = []
    for card in cards:
        last, streak, attempts = history.get(card.id, (None, 0, 0))
        # Een tentamenvraag komt pas in de planning als je hem een keer hebt
        # gemaakt. Anders staat na het importeren van één proeftentamen je hele
        # ronde vol vragen over colleges die nog moeten komen.
        if card.origin is not None and attempts == 0:
            continue
        due_at = card.created_at if last is None else last + interval_for(streak, horizon_days=horizon_days)
        if due_at <= now:
            due.append(DueCard(card=card, due_at=due_at, streak=streak, attempts=attempts))

    # Wat je vorige keer fout had gaat voorop, daarna wie het langst wacht.
    # Zonder die eerste sleutel zakt een kaart die je net miste naar de staart
    # van de rij — hij is immers "net" klaargezet — en dat is het omgekeerde
    # van wat een fout hoort te betekenen.
    due.sort(key=lambda item: (not item.lapsed, item.due_at, item.card.id))
    return due


def due_counts(db: Session, course_slug: str, *, now: datetime | None = None) -> dict[str, int]:
    """Hoeveel kaarten er per deck klaarstaan; voor de tellers in de lijst."""
    counts: dict[str, int] = {}
    for item in due_cards(db, course_slug, now=now):
        section = item.card.section_path or ""
        counts[section] = counts.get(section, 0) + 1
    return counts
