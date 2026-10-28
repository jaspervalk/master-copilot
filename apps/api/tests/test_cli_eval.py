"""CLI-tests voor `eval`: de zoekfunctie en de padcontrole worden vervangen,
zodat er geen Qdrant of netwerk nodig is."""
from app import cli
from app.core.config import settings
from app.eval.metrics import Hit


_CASES = (
    "cases:\n"
    "  - id: k1\n    course_slug: sso\n    question: vraag een\n"
    "    expected:\n      - source_path: sso/a.pdf\n        pages: [5, 6]\n"
    "  - id: k2\n    course_slug: sso\n    question: vraag twee\n"
    "    unverified: true\n"
    "    expected:\n      - source_path: sso/a.pdf\n        pages: 9\n"
)


def _prepare(tmp_path, monkeypatch, cases=_CASES, *, hits=(), known=("sso/a.pdf",)):
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "cases.yml").write_text(cases, encoding="utf-8")
    monkeypatch.setattr(settings, "eval_dir", tmp_path / "eval")
    monkeypatch.setattr(settings, "eval_runs_dir", tmp_path / "runs")
    monkeypatch.setattr(cli, "_build_search", lambda args: (lambda q, c, k: list(hits)))
    monkeypatch.setattr(cli, "_document_ids", lambda args: {path: f"id-{i}" for i, path in enumerate(known)})


def test_eval_runs_cases_and_writes_a_report(tmp_path, monkeypatch, capsys):
    _prepare(tmp_path, monkeypatch, hits=[Hit("sso/a.pdf", 6, 6, 0.7)])

    code = cli.main(["eval"])

    out = capsys.readouterr().out
    assert code == 0
    assert "totaal" in out and "1 onbevestigd" in out
    assert list((tmp_path / "runs").glob("*.json"))


def test_eval_stops_on_unknown_source_path(tmp_path, monkeypatch, capsys):
    cases = (
        "cases:\n  - id: k1\n    course_slug: sso\n    question: vraag\n"
        "    expected:\n      - source_path: sso/verhuisd.pdf\n        pages: 1\n"
    )
    _prepare(tmp_path, monkeypatch, cases)

    code = cli.main(["eval"])

    assert code == 1
    assert "sso/verhuisd.pdf" in capsys.readouterr().out
    assert not (tmp_path / "runs").exists()


def test_eval_compare_prints_delta(tmp_path, monkeypatch, capsys):
    from app.eval.report import write_report
    from app.eval.runner import CaseResult, RunReport

    cases = (
        "cases:\n  - id: k1\n    course_slug: sso\n    question: vraag\n"
        "    expected:\n      - source_path: sso/a.pdf\n        pages: 6\n"
    )
    _prepare(tmp_path, monkeypatch, cases, hits=[Hit("sso/a.pdf", 6, 6, 0.7)])
    previous = RunReport(created_at="2026-09-01T10:00:00+00:00", mode="hybrid", top_k=8)
    previous.results.append(CaseResult("k1", "sso", "vraag", rank=None, hits=[], abstain_ok=None))
    previous_path = write_report(previous, tmp_path / "runs")

    code = cli.main(["eval", "--compare", str(previous_path)])

    assert code == 0
    assert "+1.00" in capsys.readouterr().out


def test_eval_answers_flag_uses_the_answer_fn(tmp_path, monkeypatch, capsys):
    from app.eval.answers import AnswerOutcome

    _prepare(tmp_path, monkeypatch, hits=[Hit("sso/a.pdf", 6, 6, 0.7)])
    monkeypatch.setattr(
        cli, "_build_answer",
        lambda args: (lambda q, c, k, coach: AnswerOutcome("tekst", False, "high", 42)) if args.answers else None,
    )

    code = cli.main(["eval", "--answers"])

    out = capsys.readouterr().out
    assert code == 0
    assert "antwoorden: 1" in out and "42 ms" in out


def test_unreachable_api_is_one_clear_line(tmp_path, monkeypatch, capsys):
    import urllib.error

    _prepare(tmp_path, monkeypatch)

    def refused(args):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(cli, "_document_ids", refused)

    code = cli.main(["eval", "--api", "http://localhost:8000"])

    out = capsys.readouterr().out
    assert code == 1
    assert "niet bereikbaar" in out and "localhost:8000" in out
    assert "Traceback" not in out


def test_invalid_case_file_is_an_evalset_error(tmp_path, monkeypatch, capsys):
    _prepare(tmp_path, monkeypatch, "cases:\n  - id: x\n    question: geen verwachting\n")

    code = cli.main(["eval"])

    assert code == 1
    assert "evalset-fout" in capsys.readouterr().out
