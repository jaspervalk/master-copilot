"""Pure rekenfuncties over rangposities. Geen I/O, geen instellingen."""
from __future__ import annotations

from dataclasses import dataclass

from app.eval.cases import ExpectedHit


@dataclass(frozen=True)
class Hit:
    source_path: str
    page_start: int
    page_end: int
    score: float


def overlaps(hit: Hit, expected: ExpectedHit) -> bool:
    if hit.source_path != expected.source_path:
        return False
    low, high = expected.pages
    return hit.page_start <= high and hit.page_end >= low


def first_hit_rank(hits: list[Hit], expected: list[ExpectedHit]) -> int | None:
    """Positie (vanaf 1) van de eerste treffer die een verwachting overlapt."""
    for rank, hit in enumerate(hits, start=1):
        if any(overlaps(hit, item) for item in expected):
            return rank
    return None


def reciprocal_rank(rank: int | None) -> float:
    return 0.0 if rank is None else 1.0 / rank


def hit_at(rank: int | None, k: int) -> bool:
    return rank is not None and rank <= k


def summarize(ranks: list[int | None], ks: tuple[int, ...]) -> dict[str, float]:
    if not ranks:
        return {**{f"hit@{k}": 0.0 for k in ks}, "mrr": 0.0}
    total = len(ranks)
    summary = {f"hit@{k}": sum(hit_at(r, k) for r in ranks) / total for k in ks}
    summary["mrr"] = sum(reciprocal_rank(r) for r in ranks) / total
    return summary
