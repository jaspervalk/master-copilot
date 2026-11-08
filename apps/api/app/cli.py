"""Commandoregel voor het corpus en de evalset.

    python -m app.cli sync
    python -m app.cli exam-import [--course <vak>]
    python -m app.cli practice-exam --course <vak> [--count 2]
    python -m app.cli eval [--api http://localhost:8000] [--compare data/eval/runs/<run>.json]
    python -m app.cli eval-seed
    python -m app.cli canvas-sync [--dry-run]
    python -m app.cli notify [--days 3] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
from pathlib import Path

from app.core.config import settings
from app.db import SessionLocal, init_db
from app.services.canvas.client import CanvasError, client_from_settings
from app.services.canvas.sync import sync_canvas
from app.services.corpus_sync import sync_corpus
from app.services.qdrant_index import close_qdrant_client


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="Beheer het studiecorpus")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync = subparsers.add_parser("sync", help="Indexeer nieuwe en gewijzigde bestanden in corpus/")
    sync.add_argument("--course", dest="course_slug", default=None, help="Beperk tot één vak")
    sync.add_argument("--dry-run", action="store_true", help="Toon het plan zonder te schrijven")

    ev = subparsers.add_parser("eval", help="Draai de evalset tegen retrieval")
    ev.add_argument("--course", dest="course_slug", default=None, help="Beperk tot één vak")
    ev.add_argument("--top-k", dest="top_k", type=int, default=settings.default_query_limit)
    ev.add_argument("--mode", choices=["hybrid", "dense"], default="hybrid")
    ev.add_argument(
        "--api", dest="api_url", default=None,
        help="Zoek via een draaiende API in plaats van in-process",
    )
    ev.add_argument(
        "--compare", dest="compare_path", default=None,
        help="Vorige run (json) om tegen af te zetten",
    )
    ev.add_argument(
        "--cases", dest="cases_path", default=None,
        help="Ander cases-bestand dan eval/cases.yml",
    )
    ev.add_argument(
        "--answers", action="store_true",
        help="Ook het antwoordmodel meedraaien (kost per case een LLM-aanroep)",
    )

    exam = subparsers.add_parser(
        "exam-import",
        help="Zet de tentamentranscripties in corpus/<vak>/exams/*.yml om in oefenkaarten",
    )
    exam.add_argument("--course", dest="course_slug", default=None, help="Beperk tot één vak")

    practice = subparsers.add_parser(
        "practice-exam",
        help="Maak oefententamens in de opbouw van het proeftentamen in exams/",
    )
    practice.add_argument("--course", dest="course_slug", required=True)
    practice.add_argument("--count", type=int, default=1, help="Hoeveel oefententamens")

    seed = subparsers.add_parser("eval-seed", help="Maak een skelet van cases uit de query-log")
    seed.add_argument("--limit", type=int, default=20)

    canvas = subparsers.add_parser(
        "canvas-sync",
        help="Haal deadlines, quizzen, aankondigingen en materiaal uit Canvas (alleen lezen)",
    )
    canvas.add_argument("--dry-run", action="store_true", help="Tel wat er zou komen zonder te schrijven")

    notify = subparsers.add_parser("notify", help="Stuur deadlines van de komende dagen naar je telefoon (ntfy)")
    notify.add_argument("--days", type=int, default=3, help="Hoeveel dagen vooruit")
    notify.add_argument("--dry-run", action="store_true", help="Toon het bericht zonder te versturen")
    return parser


def _run_sync(args: argparse.Namespace) -> int:
    settings.prepare_runtime_directories()
    init_db()

    db = SessionLocal()
    try:
        report = sync_corpus(db, course_slug=args.course_slug, dry_run=args.dry_run)
    finally:
        db.close()
        # De embedded Qdrant-client houdt zijn opslagmap vergrendeld en klaagt
        # als hij pas tijdens het afsluiten van de interpreter wordt opgeruimd.
        close_qdrant_client()

    if args.dry_run:
        print("(dry-run — er is niets weggeschreven)")
    for line in report.as_lines():
        print(line)

    # Geweigerde paden en een kapotte course.yml zijn geen ruis maar werk:
    # laat de exitcode dat zien.
    return 1 if report.rejected or report.failed or report.course_problems or report.exam_problems else 0


# Deze drie zijn losse functies zodat de tests ze kunnen vervangen: een
# CLI-test hoort geen Qdrant, OpenAI of netwerk nodig te hebben.
def _build_search(args: argparse.Namespace):
    from app.eval.search import api_search, in_process_search

    if args.api_url:
        return api_search(args.api_url, mode=args.mode)
    return in_process_search(mode=args.mode)


def _build_answer(args: argparse.Namespace):
    from app.eval.answers import api_answer, in_process_answer

    if not args.answers:
        return None
    if args.api_url:
        return api_answer(args.api_url, mode=args.mode)
    return in_process_answer(mode=args.mode)


def _document_ids(args: argparse.Namespace) -> dict[str, str]:
    """source_path → id van alle documenten; de sleutels zijn ook de padcontrole."""
    from app.eval.search import document_ids_api, document_ids_in_process

    if args.api_url:
        return document_ids_api(args.api_url)
    init_db()
    db = SessionLocal()
    try:
        return document_ids_in_process(db)
    finally:
        db.close()


def _run_eval(args: argparse.Namespace) -> int:
    from app.eval.cases import CaseFileError, load_cases
    from app.eval.report import load_report, render_compare, render_table, write_report
    from app.eval.runner import run_cases, unknown_source_paths

    cases_path = Path(args.cases_path) if args.cases_path else settings.eval_dir / "cases.yml"
    try:
        cases = load_cases(cases_path)
    except CaseFileError as exc:
        print(f"evalset-fout: {exc}")
        return 1
    if args.course_slug:
        cases = [case for case in cases if case.course_slug == args.course_slug]

    try:
        document_ids = _document_ids(args)
    except urllib.error.URLError as exc:
        # De eerste netwerkaanroep; een dode API hoort hier één regel op te
        # leveren, geen traceback per case.
        print(f"API niet bereikbaar op {args.api_url}: {exc.reason}")
        return 1

    unknown = unknown_source_paths(cases, set(document_ids))
    if unknown:
        print("evalset verwijst naar bestanden die niet in de database staan:")
        for path in unknown:
            print(f"  {path}")
        return 1

    search = _build_search(args)
    try:
        report = run_cases(
            cases,
            search,
            top_k=args.top_k,
            mode=args.mode,
            abstain_threshold=settings.min_evidence_score,
            answer=_build_answer(args),
            document_ids=document_ids,
        )
    finally:
        if not args.api_url:
            close_qdrant_client()

    print(render_table(report))
    path = write_report(report, settings.eval_runs_dir)
    print(f"\nrun opgeslagen: {path}")

    if args.compare_path:
        print()
        print(render_compare(report, load_report(Path(args.compare_path))))
    return 0


def _run_exam_import(args: argparse.Namespace) -> int:
    """Los van `sync`, want dat heeft de Qdrant-lock nodig en dit niet: zo kan
    een verbeterde transcriptie erin terwijl de app draait."""
    from app.services.practice.exams import import_course_exams

    init_db()
    root = settings.corpus_dir
    slugs = [args.course_slug] if args.course_slug else sorted(
        path.name for path in root.iterdir() if (path / "exams").is_dir()
    )
    db = SessionLocal()
    try:
        results = [result for slug in slugs for result in import_course_exams(db, slug, root)]
    finally:
        db.close()
    for result in results:
        print(result.as_line())
    if not results:
        print("geen transcripties gevonden in corpus/<vak>/exams/")
    return 1 if any(result.problems for result in results) else 0


def _run_practice_exam(args: argparse.Namespace) -> int:
    from app.services.practice.practice_exams import NoBlueprint, generate_practice_exam

    init_db()
    db = SessionLocal()
    try:
        for _ in range(args.count):
            try:
                results = generate_practice_exam(db, args.course_slug)
            except NoBlueprint as exc:
                print(exc)
                return 1
            print(f"\n{results[0].title}: {sum(r.points for r in results):g} van {sum(r.planned_points for r in results):g} punten")
            for result in results:
                for line in result.as_lines():
                    print(f"  {line}")
    finally:
        db.close()
    return 0


def _run_eval_seed(args: argparse.Namespace) -> int:
    from app.eval.seed import render_seed_yaml, seed_entries

    init_db()
    db = SessionLocal()
    try:
        entries = seed_entries(db, limit=args.limit)
    finally:
        db.close()
    print(render_seed_yaml(entries))
    return 0


def _run_canvas_sync(args: argparse.Namespace) -> int:
    client = client_from_settings()
    if client is None:
        print("Canvas is niet geconfigureerd: zet CANVAS_BASE_URL en CANVAS_ACCESS_TOKEN in .env")
        return 1

    settings.prepare_runtime_directories()
    init_db()
    # Geen Qdrant hier: de momentopname raakt de index niet.
    db = SessionLocal()
    try:
        report = sync_canvas(db, client, dry_run=args.dry_run)
    except CanvasError as exc:
        print(f"Canvas-fout: {exc}")
        return 1
    finally:
        db.close()

    if args.dry_run:
        print("(dry-run — er is niets weggeschreven)")
    for line in report.as_lines():
        print(line)
    return 1 if report.course_problems else 0


def _run_notify(args: argparse.Namespace) -> int:
    from app.models import utcnow
    from app.services.canvas.agenda import build_agenda, local_date
    from app.services.canvas.notify import NotifyError, due_soon, message, send

    if not settings.ntfy_topic and not args.dry_run:
        print("ntfy is niet geconfigureerd: zet NTFY_TOPIC in .env")
        return 1
    settings.prepare_runtime_directories()
    init_db()
    db = SessionLocal()
    try:
        client = client_from_settings()
        if client is not None and not args.dry_run:
            # Verse deadlines; lukt Canvas niet, dan gaat de laatste momentopname uit.
            try:
                sync_canvas(db, client)
            except CanvasError as exc:
                print(f"Canvas-fout, oude gegevens gebruikt: {exc}")
        agenda = build_agenda(db)
        due = due_soon(agenda.items, agenda.tasks, args.days, today=local_date(utcnow()))
    finally:
        db.close()

    if not due:
        print("Niets binnen", args.days, "dagen")
        return 0
    print(message(due))
    if not args.dry_run:
        try:
            send(settings.ntfy_server, settings.ntfy_topic, due)
        except NotifyError as exc:
            print(f"Melding niet verstuurd: {exc}")
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "sync":
        return _run_sync(args)
    if args.command == "canvas-sync":
        return _run_canvas_sync(args)
    if args.command == "notify":
        return _run_notify(args)
    if args.command == "eval":
        return _run_eval(args)
    if args.command == "exam-import":
        return _run_exam_import(args)
    if args.command == "practice-exam":
        return _run_practice_exam(args)
    if args.command == "eval-seed":
        return _run_eval_seed(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
