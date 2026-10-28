"""Externe uitleg, en de onderbouwing van de manier van oefenen.

Twee lijsten in `resources/library.yml`, met de hand bijgehouden:

* `resources` — gratis uitleg (video, interactief, tekstboek) die aan een
  onderwerp uit je `course.yml` hangt. Alles wordt alleen gelinkt, nooit
  binnengehaald: het corpus blijft je eigen materiaal, en van de meeste bronnen
  mag het ook niet. De licentie staat er daarom bij.
* `method` — waarom het oefenprogramma doet wat het doet, met de studie erbij.
  Niet als sier: wie de keuzes niet kan nalezen, kan ze ook niet wantrouwen.

De koppeling gokt niet. Een bron verschijnt bij een onderwerp als een van zijn
trefwoorden er als heel woord in staat. Staat er niets, dan staat er niets.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR
from app.models import Course


LIBRARY_PATH = ROOT_DIR / "resources" / "library.yml"


@dataclass(frozen=True)
class Resource:
    name: str
    url: str
    kind: str
    license: str
    note: str
    topics: list[str]


@dataclass(frozen=True)
class MethodClaim:
    claim: str
    source: str
    title: str
    url: str
    strength: str


@dataclass
class Library:
    resources: list[Resource] = field(default_factory=list)
    method: list[MethodClaim] = field(default_factory=list)


@dataclass
class TopicResources:
    week: int
    topic: str
    resources: list[Resource] = field(default_factory=list)


@lru_cache(maxsize=1)
def load_library(path: Path | None = None) -> Library:
    """De lijst van schijf. Gecached: hij verandert alleen als jij hem aanpast."""
    target = path or LIBRARY_PATH
    if not target.exists():
        return Library()

    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return Library(
        resources=[
            Resource(
                name=str(entry.get("name", "")),
                url=str(entry.get("url", "")),
                kind=str(entry.get("kind", "")),
                license=str(entry.get("license", "")),
                note=str(entry.get("note", "")),
                topics=[str(topic).lower() for topic in (entry.get("topics") or [])],
            )
            for entry in (raw.get("resources") or [])
        ],
        method=[
            MethodClaim(
                claim=str(entry.get("claim", "")),
                source=str(entry.get("source", "")),
                title=str(entry.get("title", "")),
                url=str(entry.get("url", "")),
                strength=str(entry.get("strength", "")),
            )
            for entry in (raw.get("method") or [])
        ],
    )


def matches(resource: Resource, topic: str) -> bool:
    """Staat een trefwoord van deze bron als heel woord in dit onderwerp?

    Op woordgrens, want anders slaat "gam" aan op "gamma distribution" — en een
    verkeerde link kost je meer tijd dan geen link.
    """
    lowered = topic.lower()
    return any(re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", lowered) for word in resource.topics)


def topics_with_resources(
    db: Session, course_slug: str, *, resources: list[Resource] | None = None
) -> list[TopicResources]:
    """Elk onderwerp van dit vak, in weekvolgorde, met wat erbij past."""
    course = db.get(Course, course_slug)
    if course is None:
        return []

    beschikbaar = load_library().resources if resources is None else resources

    rijen: list[TopicResources] = []
    for key, plan in sorted((course.week_plans or {}).items(), key=lambda item: int(item[0])):
        for topic in (plan or {}).get("topics") or []:
            rijen.append(
                TopicResources(
                    week=int(key),
                    topic=topic,
                    resources=[resource for resource in beschikbaar if matches(resource, topic)],
                )
            )
    return rijen
