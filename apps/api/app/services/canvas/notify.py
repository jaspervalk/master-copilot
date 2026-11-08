"""Deadline push to a phone via ntfy (https://ntfy.sh): one message listing
what is due in the next few days. The topic name is the only secret: anyone
who knows it can read the messages, so keep it long and random."""

from __future__ import annotations

import urllib.request

from app.schemas import AgendaItemRead

FINISHED = {"submitted", "late", "graded", "done", "closed", "past"}


def due_soon(items: list[AgendaItemRead], days: int) -> list[AgendaItemRead]:
    soon = [i for i in items if i.days_left is not None and 0 <= i.days_left <= days and i.status not in FINISHED]
    return sorted(soon, key=lambda i: i.days_left)


def _when(days_left: int) -> str:
    if days_left == 0:
        return "today"
    if days_left == 1:
        return "tomorrow"
    return f"in {days_left} days"


def message(items: list[AgendaItemRead]) -> str:
    return "\n".join(f"{_when(i.days_left)}: {i.course_name} - {i.title}" for i in items)


def send(server: str, topic: str, items: list[AgendaItemRead]) -> None:
    urgent = items[0].days_left <= 1
    request = urllib.request.Request(
        f"{server.rstrip('/')}/{topic}",
        data=message(items).encode("utf-8"),
        headers={"Title": f"{len(items)} deadline(s) coming up", "Priority": "high" if urgent else "default"},
    )
    urllib.request.urlopen(request, timeout=30).close()
