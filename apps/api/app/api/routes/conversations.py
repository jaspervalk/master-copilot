from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Conversation
from app.schemas import ConversationDetail, ConversationRead, MessageRead


router = APIRouter()


@router.get("/conversations", response_model=list[ConversationRead])
def list_conversations(db: Annotated[Session, Depends(get_db)]) -> list[ConversationRead]:
    stmt = select(Conversation).order_by(Conversation.updated_at.desc())
    return [ConversationRead.model_validate(item) for item in db.scalars(stmt)]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, db: Annotated[Session, Depends(get_db)]) -> ConversationDetail:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Gesprek niet gevonden")
    detail = ConversationDetail.model_validate(conversation)
    detail.messages = [MessageRead.model_validate(message) for message in conversation.messages]
    return detail
