"""De coach kent de opdracht, niet jouw uitwerking.

De gekozen opdracht wordt gepind in het bewijs zodat het model de echte
opgavetekst ziet, en het beleid volgt uit de soort: beoordeeld is altijd
hints; oefenmateriaal is hints tot je om de uitwerking vraagt.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Document
from app.schemas import CoachEcho, CoachOptions, CoachPolicy, QueryChunkResult


# Een opgavenblad is kort; dit plafond beschermt alleen tegen een verkeerd
# gekozen document van honderd pagina's.
MAX_PINNED = 12
COACHABLE_KINDS = ("assignment", "exercise")


class CoachError(ValueError):
    """Het gekozen document is geen open opdracht of oefening van dit vak."""


@dataclass
class CoachContext:
    document_id: str
    document_title: str
    doc_kind: str
    policy: CoachPolicy
    pinned: list[QueryChunkResult]
    echo: CoachEcho


def load_coach_context(db: Session, options: CoachOptions, course_slug: str | None) -> CoachContext:
    document = db.scalar(
        select(Document).options(selectinload(Document.chunks)).where(Document.id == options.document_id)
    )
    if document is None:
        raise CoachError(f"Opdracht {options.document_id} niet gevonden")
    if document.doc_kind not in COACHABLE_KINDS:
        raise CoachError(f"'{document.title}' is een {document.doc_kind}, geen opdracht of oefening")
    if course_slug and document.course_slug != course_slug:
        raise CoachError(f"'{document.title}' hoort bij {document.course_slug}, niet bij {course_slug}")
    if document.doc_kind == "assignment" and document.assignment_status != "open":
        raise CoachError(
            f"'{document.title}' is {document.assignment_status}; coachen heeft alleen zin op een open opdracht"
        )

    # Beoordeeld blijft hints, ook als de UI reveal meestuurt.
    policy: CoachPolicy = "reveal" if document.doc_kind == "exercise" and options.reveal else "hints"

    pinned = [
        QueryChunkResult(
            chunk_id=chunk.id,
            document_id=document.id,
            document_title=document.title,
            source_path=document.source_path,
            course_slug=document.course_slug,
            doc_kind=document.doc_kind,
            week=document.week,
            assignment_status=document.assignment_status,
            section_path=chunk.section_path,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            score=1.0,
            text=chunk.text,
            chunk_metadata=chunk.chunk_metadata,
        )
        for chunk in document.chunks[:MAX_PINNED]
    ]
    echo = CoachEcho(document_id=document.id, document_title=document.title, policy=policy)
    return CoachContext(
        document_id=document.id,
        document_title=document.title,
        doc_kind=document.doc_kind,
        policy=policy,
        pinned=pinned,
        echo=echo,
    )


_HINTS = (
    "Je begeleidt een student bij een opdracht. Geef nooit het eindantwoord: geen uitkomst, "
    "geen volledige code, geen volledige afleiding. Geef wél de eerstvolgende stap, het begrip "
    "dat erachter zit, en waar dat in het materiaal staat. Vraag wat de student al heeft "
    "geprobeerd als dat niet duidelijk is. Gaat de vraag niet over de opdracht, antwoord dan gewoon."
)
_HINTS_EXERCISE = " De student kan om de volledige uitwerking vragen; verwijs daar niet zelf naar."
_REVEAL = (
    "Geef de volledige uitwerking van de opgave, stap voor stap, met bij elke stap de vindplaats "
    "in het materiaal. Sluit af met wat de student moet onthouden voor het tentamen."
)


def policy_instruction(policy: CoachPolicy, doc_kind: str) -> str:
    if policy == "reveal":
        return _REVEAL
    return _HINTS + (_HINTS_EXERCISE if doc_kind == "exercise" else "")
