"""Tabel naar stdout, JSON naar schijf, en de delta tussen twee runs.

Het JSON-bestand bestaat om één reden: een verandering aan retrieval moet in
één regel te beoordelen zijn tegen de vorige run.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.eval.answers import AnswerOutcome
from app.eval.metrics import Hit, summarize
from app.eval.runner import CaseResult, RunReport


KS = (1, 3, 5)


def _by_course(report: RunReport) -> dict[str, list[CaseResult]]:
    groups: dict[str, list[CaseResult]] = {}
    for result in report.results:
        groups.setdefault(result.course_slug or "—", []).append(result)
    return groups


def _ranked(results: list[CaseResult]) -> list[CaseResult]:
    return [r for r in results if r.error is None and r.abstain_ok is None]


def _row(label: str, results: list[CaseResult], ks: tuple[int, ...]) -> str:
    ranked = _ranked(results)
    summary = summarize([r.rank for r in ranked], ks)
    cells = "".join(f"{summary[f'hit@{k}']:8.2f}" for k in ks) + f"{summary['mrr']:8.2f}"
    return f"{label:<16}({len(ranked):>3}){cells}"


def render_table(report: RunReport, ks: tuple[int, ...] = KS) -> str:
    lines = [
        f"eval  {report.created_at}  {len(report.results)} cases  {report.mode}  top_k={report.top_k}"
    ]
    if report.skipped_unverified:
        lines[0] += f"  ({report.skipped_unverified} onbevestigd overgeslagen)"
    header = "".join(f"{f'hit@{k}':>8}" for k in ks) + f"{'mrr':>8}"
    lines.append(f"{'':<21}{header}")
    for course, results in sorted(_by_course(report).items()):
        lines.append(_row(course, results, ks))
    lines.append(_row("totaal", report.results, ks))

    abstains = [r for r in report.results if r.abstain_ok is not None]
    if abstains:
        ok = sum(1 for r in abstains if r.abstain_ok)
        lines.append(f"\nabstain: {ok}/{len(abstains)} goed")

    misses = [r for r in _ranked(report.results) if r.rank is None or r.rank > 3]
    if misses:
        lines.append("\ngemist in top-3:")
        for result in misses:
            got = " ".join(f"p{hit.page_start}" for hit in result.hits[:3]) or "niets"
            where = f"rang {result.rank}" if result.rank else "niet gevonden"
            lines.append(f"  {result.case_id:<22} {where:<14} top-3: {got}")

    answered = [r for r in report.results if r.answer is not None]
    if answered:
        latencies = [r.answer.latency_ms for r in answered if r.answer.latency_ms is not None]
        high = sum(1 for r in answered if r.answer.confidence == "high")
        mentions = [r for r in answered if r.mentions_ok is not None]
        line = f"\nantwoorden: {len(answered)}  hoog vertrouwen {high}/{len(answered)}"
        if latencies:
            line += f"  mediaan {sorted(latencies)[len(latencies) // 2]} ms"
        if mentions:
            line += f"  must_mention {sum(1 for r in mentions if r.mentions_ok)}/{len(mentions)}"
        leaked = [r for r in answered if r.leaks]
        if leaked:
            line += f"  lekkage {len(leaked)}/{len(answered)}"
            for result in leaked:
                line += f"\n  lek {result.case_id:<22} {', '.join(result.leaks)}"
        lines.append(line)

    errors = [r for r in report.results if r.error]
    if errors:
        lines.append("\nfouten:")
        for result in errors:
            lines.append(f"  {result.case_id:<22} {result.error}")
    return "\n".join(lines)


def write_report(report: RunReport, runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.created_at.replace(":", "").replace("+0000", "Z")
    path = runs_dir / f"{stamp}.json"
    path.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_report(path: Path) -> RunReport:
    raw = json.loads(path.read_text(encoding="utf-8"))
    results = [
        CaseResult(
            case_id=item["case_id"],
            course_slug=item["course_slug"],
            question=item["question"],
            rank=item["rank"],
            hits=[Hit(**hit) for hit in item["hits"]],
            abstain_ok=item["abstain_ok"],
            error=item.get("error"),
            answer=AnswerOutcome(**item["answer"]) if item.get("answer") else None,
            mentions_ok=item.get("mentions_ok"),
        )
        for item in raw["results"]
    ]
    return RunReport(
        created_at=raw["created_at"],
        mode=raw["mode"],
        top_k=raw["top_k"],
        results=results,
        skipped_unverified=raw.get("skipped_unverified", 0),
    )


def render_compare(current: RunReport, previous: RunReport, ks: tuple[int, ...] = KS) -> str:
    now = summarize([r.rank for r in _ranked(current.results)], ks)
    before = summarize([r.rank for r in _ranked(previous.results)], ks)
    lines = [f"vergeleken met {previous.created_at}:"]
    for key in [*(f"hit@{k}" for k in ks), "mrr"]:
        delta = now[key] - before[key]
        lines.append(f"  {key:<8}{before[key]:6.2f} -> {now[key]:6.2f}   {delta:+.2f}")

    previous_rank = {r.case_id: r.rank for r in previous.results}
    worse = [
        r
        for r in current.results
        if r.case_id in previous_rank
        and previous_rank[r.case_id] is not None
        and (r.rank is None or r.rank > previous_rank[r.case_id])
    ]
    if worse:
        lines.append("\nslechter dan vorige run:")
        for result in worse:
            lines.append(
                f"  {result.case_id:<22} rang {previous_rank[result.case_id]} -> {result.rank or 'niet gevonden'}"
            )
    return "\n".join(lines)
