"""Wat er nu aandacht vraagt — voor de tellers in de navigatiebalk."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import AttentionRead
from app.services.attention import attention

router = APIRouter(tags=["attention"])


@router.get("/attention", response_model=AttentionRead)
def get_attention(db: Annotated[Session, Depends(get_db)]) -> AttentionRead:
    telling = attention(db)
    return AttentionRead(today=telling.today, overdue=telling.overdue, due_cards=telling.due_cards)
