"""Gesprekken en het zelfstandig maken van vervolgvragen.

"En waarom is dat convex dan?" is zonder de vorige beurt onvindbaar. Voor het
ophalen wordt zo'n vraag eerst herschreven tot een zelfstandige zoekvraag; het
antwoordmodel krijgt daarnaast de laatste beurten mee.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Conversation, Message
from app.schemas import AnswerResponse


logger = logging.getLogger(__name__)

HISTORY_LIMIT = 6
_TITLE_LENGTH = 120

_REWRITE_INSTRUCTIONS = (
    "Herschrijf de laatste vraag tot één zelfstandige zoekvraag die zonder de voorgaande "
    "beurten te begrijpen is. Behoud vaktermen en notatie letterlijk. Antwoord met alleen "
    "die vraag, zonder aanhalingstekens en zonder toelichting."
)


def get_or_create(db: Session, conversation_id: str | None, *, course_slug: str | None) -> Conversation:
    if conversation_id:
        existing = db.get(Conversation, conversation_id)
        if existing is not None:
            return existing

    conversation = Conversation(course_slug=course_slug)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def history(db: Session, conversation_id: str, *, limit: int = HISTORY_LIMIT) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    return list(reversed(list(db.scalars(stmt))))


def rewrite_followup(
    *,
    history: list[Message],
    question: str,
    client=None,
    model: str | None = None,
) -> str | None:
    """Geef de zelfstandige zoekvraag, of None als er niets te herschrijven valt.

    None betekent: gebruik de vraag zoals hij is. Dat is ook de uitkomst als het
    model niet beschikbaar is of faalt — een mislukte herschrijving mag nooit
    het hele antwoord tegenhouden.
    """
    if not history or client is None:
        return None

    transcript = "\n".join(f"{message.role}: {message.content}" for message in history)
    try:
        response = client.responses.create(
            model=model or settings.openai_rewrite_model,
            instructions=_REWRITE_INSTRUCTIONS,
            input=f"Gesprek tot nu toe:\n{transcript}\n\nLaatste vraag: {question}",
        )
        rewritten = (getattr(response, "output_text", "") or "").strip()
    except Exception:
        logger.exception("Herschrijven van de vervolgvraag mislukte; originele vraag wordt gebruikt.")
        return None

    if not rewritten or rewritten.lower() == question.strip().lower():
        return None
    return rewritten


def record_turn(
    db: Session,
    conversation: Conversation,
    *,
    question: str,
    answer: AnswerResponse,
) -> tuple[Message, Message]:
    user_message = Message(conversation_id=conversation.id, role="user", content=question)
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=answer.answer,
        rewritten_query=answer.rewritten_query,
        citations=[citation.model_dump(mode="json") for citation in answer.citations],
        confidence=answer.confidence,
        abstained=answer.abstained,
    )
    db.add_all([user_message, assistant_message])

    if not conversation.title:
        conversation.title = question[:_TITLE_LENGTH]

    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)
    return user_message, assistant_message
