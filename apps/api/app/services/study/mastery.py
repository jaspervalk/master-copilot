"""Wat je van een kaart al weet, afgeleid uit je pogingen.

Dezelfde keuze als bij de herhaling (`practice/scheduling.py`): niets apart
bijhouden. `practice_attempts` legt al vast wat er gebeurde, en een tweede
administratie ernaast kan uit de pas lopen — precies het soort stille fout waar
je pas achter komt als je er al een week op vertrouwde.

Beheersing is hier mechanisch gedefinieerd, niet geschat: een reeks van drie
goede antwoorden op verschillende momenten. Dat is geen uitspraak over of je
het "echt snapt"; het is wat de gegevens dragen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, PracticeAttempt, PracticeCard, utcnow
from app.services.practice.scheduling import interval_for


NIEUW = "nieuw"
LEREND = "lerend"
BEHEERST = "beheerst"
ZWAK = "zwak"

# Drie goede antwoorden op rij. Op de Leitner-ladder staat de kaart dan op een
# interval van een week, en dat is het eerste punt waarop "ik kan dit" meer is
# dan "ik heb hem net gezien".
MASTERY_STREAK = 3


@dataclass(frozen=True)
class CardState:
    card_id: str
    kind: str
    week: int | None
    topic: str | None
    section_path: str | None
    state: str
    streak: int
    attempts: int
    # Wanneer hij weer aan de beurt is; in het verleden betekent: nu.
    due_at: datetime
    last_at: datetime | None

    @property
    def due(self) -> bool:
        return self.due_at <= utcnow()


def state_for(streak: int, attempts: int) -> str:
    if attempts == 0:
        return NIEUW
    if streak == 0:
        return ZWAK
    return BEHEERST if streak >= MASTERY_STREAK else LEREND


def _history(db: Session, card_ids: list[str]) -> dict[str, tuple[datetime, int, int]]:
    """Per kaart: laatste poging, de reeks goede antwoorden tot nu, en het totaal."""
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
        history[card_id] = (moment, streak + 1 if correct else 0, total + 1)
    return history


def card_states(
    db: Session,
    course_slug: str,
    *,
    now: datetime | None = None,
    horizon_days: int | None = None,
) -> list[CardState]:
    """De staat van elke levende kaart van dit vak."""
    now = now or utcnow()

    cards = list(
        db.scalars(
            select(PracticeCard).where(
                PracticeCard.course_slug == course_slug,
                PracticeCard.disabled.is_(False),
            )
        )
    )
    if not cards:
        return []

    # De week staat pas sinds deze plak op de kaart zelf. Wat er al lag, erft
    # hem van zijn document — anders valt je hele bestaande oefenset buiten het
    # weekoverzicht en lijkt het alsof je nog niets hebt.
    weeks = dict(
        db.execute(
            select(Document.id, Document.week).where(
                Document.id.in_({card.document_id for card in cards})
            )
        ).all()
    )

    history = _history(db, [card.id for card in cards])

    states: list[CardState] = []
    for card in cards:
        last, streak, attempts = history.get(card.id, (None, 0, 0))
        states.append(
            CardState(
                card_id=card.id,
                kind=card.kind,
                week=card.week if card.week is not None else weeks.get(card.document_id),
                topic=(card.spec or {}).get("topic") or None,
                section_path=card.section_path,
                state=state_for(streak, attempts),
                streak=streak,
                attempts=attempts,
                due_at=(
                    card.created_at if last is None else last + interval_for(streak, horizon_days=horizon_days)
                ),
                last_at=last,
            )
        )
    return states
