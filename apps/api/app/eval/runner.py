"""Cases × zoekfunctie → per-case-resultaat.

De zoekfunctie wordt geïnjecteerd: in-process via RetrievalService of over
HTTP via /api/query. De runner weet niet welke, en de tests hebben geen van
beide nodig.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.eval.answers import AnswerFn, AnswerOutcome, leaked_terms, mentions_ok
from app.eval.cases import EvalCase
from app.eval.metrics import Hit, first_hit_rank


SearchFn = Callable[[str, str | None, int], list[Hit]]


@dataclass
class CaseResult:
    case_id: str
    course_slug: str | None
    question: str
    rank: int | None
    hits: list[Hit]
    # Alleen gevuld voor cases met expect_abstain; None betekent "niet van toepassing".
    abstain_ok: bool | None
    error: str | None = None
    # Alleen gevuld met --answers.
    answer: AnswerOutcome | None = None
    mentions_ok: bool | None = None
    # Verboden termen die tóch in het antwoord stonden.
    leaks: list[str] = field(default_factory=list)


@dataclass
class RunReport:
    created_at: str
    mode: str
    top_k: int
    results: list[CaseResult] = field(default_factory=list)
    skipped_unverified: int = 0


def unknown_source_paths(cases: list[EvalCase], known: set[str]) -> list[str]:
    """Verwachte paden die niet in de database staan.

    Een verhuisd bestand is een evalset-fout, geen retrievalfout; die hoort de
    run te stoppen in plaats van als 'miss' mee te tellen.
    """
    unknown: list[str] = []
    for case in cases:
        for item in case.expected:
            if item.source_path not in known and item.source_path not in unknown:
                unknown.append(item.source_path)
    return unknown


def run_cases(
    cases: list[EvalCase],
    search: SearchFn,
    *,
    top_k: int,
    mode: str,
    abstain_threshold: float,
    answer: AnswerFn | None = None,
    document_ids: dict[str, str] | None = None,
) -> RunReport:
    report = RunReport(
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        mode=mode,
        top_k=top_k,
    )

    for case in cases:
        if case.unverified:
            report.skipped_unverified += 1
            continue

        try:
            hits = search(case.question, case.course_slug, top_k)
        except Exception as exc:  # noqa: BLE001 — één kapotte case stopt de run niet
            report.results.append(
                CaseResult(
                    case.id, case.course_slug, case.question,
                    rank=None, hits=[], abstain_ok=None, error=str(exc),
                )
            )
            continue

        # Een coach-case wijst naar een source_path; de antwoordfunctie wil een
        # document_id. Onbekend pad is een evalset-fout, geen antwoordfout.
        coach_payload: dict | None = None
        if case.coach is not None:
            document_id = (document_ids or {}).get(case.coach.document)
            if document_id is None:
                report.results.append(
                    CaseResult(
                        case.id, case.course_slug, case.question, rank=None, hits=hits,
                        abstain_ok=None, error=f"coach-document niet gevonden: {case.coach.document}",
                    )
                )
                continue
            coach_payload = {"document_id": document_id, "reveal": case.coach.reveal}

        outcome: AnswerOutcome | None = None
        answer_error: str | None = None
        if answer is not None:
            try:
                outcome = answer(case.question, case.course_slug, top_k, coach_payload)
            except Exception as exc:  # noqa: BLE001 — retrieval blijft geldig
                answer_error = f"antwoord: {exc}"

        abstain_ok: bool | None = None
        if case.expect_abstain:
            if outcome is not None:
                abstain_ok = outcome.abstained
            else:
                # Zonder antwoordmodel is "niets relevants" het best te benaderen
                # als: geen enkele treffer haalt de drempel die het antwoord ook
                # hanteert. Zo wordt die drempel meteen meetbaar.
                abstain_ok = all(hit.score < abstain_threshold for hit in hits)

        report.results.append(
            CaseResult(
                case_id=case.id,
                course_slug=case.course_slug,
                question=case.question,
                rank=first_hit_rank(hits, case.expected) if case.expected else None,
                hits=hits,
                abstain_ok=abstain_ok,
                error=answer_error,
                answer=outcome,
                mentions_ok=mentions_ok(outcome.text, case.must_mention) if outcome else None,
                leaks=leaked_terms(outcome.text, case.must_not_mention) if outcome else [],
            )
        )
    return report
