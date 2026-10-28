from app.eval.metrics import Hit
from app.eval.report import load_report, render_compare, render_table, write_report
from app.eval.runner import CaseResult, RunReport


def _report(ranks, mode="hybrid"):
    report = RunReport(created_at="2026-09-02T14:03:00+00:00", mode=mode, top_k=8)
    for index, (course, rank) in enumerate(ranks):
        report.results.append(
            CaseResult(
                case_id=f"c{index}", course_slug=course, question=f"vraag {index}",
                rank=rank, hits=[Hit("a.pdf", 1, 2, 0.5)], abstain_ok=None,
            )
        )
    return report


def test_table_has_a_row_per_course_and_a_total():
    table = render_table(_report([("sso", 1), ("sso", None), ("fds", 2)]), ks=(1, 3))

    assert "sso" in table and "fds" in table and "totaal" in table
    # sso: hit@1 = 1/2, fds: hit@1 = 0/1, totaal hit@1 = 1/3
    assert "0.50" in table and "0.33" in table


def test_table_lists_misses_outside_top_three():
    report = _report([("sso", None), ("sso", 4)])
    report.results[0].hits = [Hit("a.pdf", 7, 7, 0.4)]

    table = render_table(report, ks=(1, 3))

    assert "gemist in top-3" in table
    assert "c0" in table and "c1" in table
    assert "p7" in table


def test_table_reports_skipped_and_errors():
    report = _report([("sso", 1)])
    report.skipped_unverified = 2
    report.results[0].error = "netwerk weg"

    table = render_table(report, ks=(1,))

    assert "2 onbevestigd" in table
    assert "netwerk weg" in table


def test_write_then_load_round_trips(tmp_path):
    report = _report([("sso", 1), ("fds", None)])

    path = write_report(report, tmp_path / "runs")
    loaded = load_report(path)

    assert path.parent == tmp_path / "runs"
    assert loaded.created_at == report.created_at
    assert [r.rank for r in loaded.results] == [1, None]
    assert loaded.results[0].hits[0].source_path == "a.pdf"


def test_compare_shows_delta_per_metric():
    current = _report([("sso", 1), ("sso", 1)])
    previous = _report([("sso", 1), ("sso", None)])

    text = render_compare(current, previous, ks=(1,))

    assert "hit@1" in text
    assert "+0.50" in text


def test_compare_names_cases_that_got_worse():
    current = _report([("sso", None)])
    previous = _report([("sso", 1)])

    text = render_compare(current, previous, ks=(1,))

    assert "slechter" in text and "c0" in text
