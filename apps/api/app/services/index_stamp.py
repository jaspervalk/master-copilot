from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IndexCollection


@dataclass
class IndexStamp:
    name: str
    provider: str
    model: str
    dimensions: int


class StampMismatchError(RuntimeError):
    """Raised when current embedder does not match the stamped collection."""


def read_stamp(db: Session, name: str) -> IndexStamp | None:
    row = db.scalar(select(IndexCollection).where(IndexCollection.name == name))
    if row is None:
        return None
    return IndexStamp(name=row.name, provider=row.provider, model=row.model, dimensions=row.dimensions)


def write_stamp(db: Session, *, name: str, provider: str, model: str, dimensions: int) -> IndexStamp:
    row = db.scalar(select(IndexCollection).where(IndexCollection.name == name))
    if row is None:
        row = IndexCollection(name=name, provider=provider, model=model, dimensions=dimensions)
        db.add(row)
    else:
        row.provider = provider
        row.model = model
        row.dimensions = dimensions
    db.flush()
    return IndexStamp(name=name, provider=provider, model=model, dimensions=dimensions)


def validate_or_raise(
    stamp: IndexStamp | None,
    *,
    provider: str,
    model: str,
    dimensions: int,
) -> None:
    if stamp is None:
        return
    if stamp.provider != provider or stamp.model != model or stamp.dimensions != dimensions:
        raise StampMismatchError(
            f"Index collection '{stamp.name}' is stamped "
            f"({stamp.provider}, {stamp.model}, {stamp.dimensions}) but the current "
            f"embedder is ({provider}, {model}, {dimensions}). "
            "Wipe the collection and reindex, or revert the embedding settings."
        )
