"""Skelet-cases uit de echte query-log.

De opgehaalde toppagina van toen is een *kandidaat*, geen waarheid: het is
wat het systeem deed, niet wat het had moeten doen. Daarom staat elke case op
`unverified: true` en draait de runner ze niet mee tot iemand dat veld weghaalt.
"""
from __future__ import annotations

import hashlib
import re

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import QueryLog


_HEADER = """# Gegenereerd door `python -m app.cli eval-seed`.
# Elke case is nog niet nagekeken: de verwachting is wat retrieval destijds
# bovenaan zette. Controleer het paginabereik in het boek, pas het aan, en haal
# `unverified: true` weg. Zolang dat veld er staat draait de case niet mee.
"""


def _normalized(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


def _case_id(question: str) -> str:
    return "seed-" + hashlib.sha1(_normalized(question).encode("utf-8")).hexdigest()[:8]


def seed_entries(db: Session, *, limit: int) -> list[dict]:
    stmt = (
        select(QueryLog)
        .where(QueryLog.status == "ok")
        .order_by(QueryLog.created_at.desc())
    )
    entries: list[dict] = []
    seen: set[str] = set()
    for log in db.scalars(stmt):
        key = _normalized(log.question)
        if key in seen or not log.citations:
            continue
        seen.add(key)
        first = log.citations[0]
        entries.append(
            {
                "id": _case_id(log.question),
                "course_slug": (log.filters or {}).get("course_slug"),
                "question": log.question,
                "unverified": True,
                "expected": [
                    {
                        "source_path": first["source_path"],
                        "pages": [int(first["page_start"]), int(first["page_end"])],
                    }
                ],
            }
        )
        if len(entries) >= limit:
            break
    return entries


def render_seed_yaml(entries: list[dict]) -> str:
    body = yaml.safe_dump({"cases": entries}, allow_unicode=True, sort_keys=False)
    return _HEADER + "\n" + body
