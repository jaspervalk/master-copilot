"""Deadlines op je telefoon via ntfy (https://ntfy.sh): één bericht met wat er
de komende dagen af moet. De topicnaam is het enige geheim: wie hem kent, leest
mee. Hij hoort dus niet in een foutmelding of een log.

Stdlib `urllib` met een injecteerbare `opener`, net als de Canvas-client.
"""
from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from app.schemas import AgendaItemRead, TaskRead
from app.services.canvas.client import _default_opener

# Waar niets meer op tijd aan te doen is, of geen datum voor bestaat. De bucket
# komt uit `bucket_for`: een eigen statuslijst zou kunnen gaan afwijken van de
# agenda, en `days_left` alleen zegt niet dat een deadline van vanochtend voorbij is.
_NOT_DUE = frozenset({"done", "overdue", "undated"})

# Een Mac die net wakker is heeft nog geen wifi, en launchd probeert het pas de
# volgende ochtend opnieuw. Seconden tussen de pogingen.
_PAUSES = (30, 120)


class NotifyError(Exception):
    """Niet verstuurd. Noemt de status of de oorzaak, nooit het topic."""


@dataclass(frozen=True)
class Due:
    days_left: int
    label: str


def due_soon(items: list[AgendaItemRead], tasks: list[TaskRead], days: int, *, today: date) -> list[Due]:
    # Een kalenderitem is een college, geen deadline. Het kreeg anders bijna elke
    # dag hoge prioriteit, en dan zie je de echte deadline niet meer staan.
    due = [
        Due(item.days_left, f"{item.course_name} - {item.title}")
        for item in items
        if item.kind != "event" and item.days_left is not None and item.bucket not in _NOT_DUE
    ]
    due += [Due((task.due_on - today).days, task.title) for task in tasks if task.due_on and task.bucket not in _NOT_DUE]
    return sorted((entry for entry in due if entry.days_left <= days), key=lambda entry: entry.days_left)


def _when(days_left: int) -> str:
    if days_left == 0:
        return "vandaag"
    if days_left == 1:
        return "morgen"
    return f"over {days_left} dagen"


def message(due: list[Due]) -> str:
    return "\n".join(f"{_when(entry.days_left)}: {entry.label}" for entry in due)


def _title(count: int) -> str:
    return f"{count} deadline binnenkort" if count == 1 else f"{count} deadlines binnenkort"


def send(
    server: str,
    topic: str,
    due: list[Due],
    *,
    opener: Callable = _default_opener,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    urgent = min(entry.days_left for entry in due) <= 1
    request = urllib.request.Request(
        f"{server.rstrip('/')}/{topic}",
        data=message(due).encode("utf-8"),
        headers={"Title": _title(len(due)), "Priority": "high" if urgent else "default"},
        method="POST",
    )
    for pause in (*_PAUSES, None):
        try:
            opener(request, timeout=30).close()
            return
        except urllib.error.HTTPError as exc:
            reason = f"ntfy antwoordde {exc.code}"
            if exc.code < 500 and exc.code != 429:
                # `from None`: de oorspronkelijke fout draagt de URL, mét topic.
                raise NotifyError(reason) from None
        except urllib.error.URLError as exc:
            reason = f"ntfy onbereikbaar: {exc.reason}"
        except (OSError, http.client.HTTPException) as exc:
            reason = f"ntfy onbereikbaar: {exc}"
        if pause is None:
            raise NotifyError(reason) from None
        sleep(pause)
