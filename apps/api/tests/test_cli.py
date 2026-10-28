from app import cli
from app.services.corpus_sync import SyncReport


class _FakeSession:
    def close(self) -> None:
        pass


def test_sync_prints_a_summary(monkeypatch, capsys):
    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        cli,
        "sync_corpus",
        lambda db, course_slug=None, dry_run=False: SyncReport(added=2, skipped=1),
    )

    exit_code = cli.main(["sync"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "toegevoegd: 2" in output
    assert "ongewijzigd: 1" in output


def test_rejected_paths_make_the_command_fail(monkeypatch, capsys):
    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        cli,
        "sync_corpus",
        lambda db, course_slug=None, dry_run=False: SyncReport(
            rejected=[("dl/random/x.pdf", "Onbekende map 'random'")]
        ),
    )

    exit_code = cli.main(["sync"])

    assert exit_code == 1
    assert "geweigerd" in capsys.readouterr().out


def test_canvas_sync_prints_the_report(monkeypatch, capsys):
    from app.services.canvas.sync import CanvasSyncReport

    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(cli, "client_from_settings", lambda: object())
    monkeypatch.setattr(
        cli, "sync_canvas", lambda db, client, dry_run=False: CanvasSyncReport(courses=3, items=8, files_new=2)
    )

    exit_code = cli.main(["canvas-sync"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "vakken: 3" in output
    assert "nieuw materiaal: 2" in output


def test_canvas_sync_without_configuration_fails_readably(monkeypatch, capsys):
    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "client_from_settings", lambda: None)

    exit_code = cli.main(["canvas-sync"])

    assert exit_code == 1
    assert "CANVAS_ACCESS_TOKEN" in capsys.readouterr().out


def test_canvas_sync_reports_a_canvas_error_without_a_traceback(monkeypatch, capsys):
    from app.services.canvas.client import CanvasError

    def broken(db, client, dry_run=False):
        raise CanvasError(401, "courses")

    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(cli, "client_from_settings", lambda: object())
    monkeypatch.setattr(cli, "sync_canvas", broken)

    exit_code = cli.main(["canvas-sync"])

    assert exit_code == 1
    assert "401" in capsys.readouterr().out


def test_canvas_sync_dry_run_is_passed_through(monkeypatch, capsys):
    from app.services.canvas.sync import CanvasSyncReport

    captured = {}

    def fake_sync(db, client, dry_run=False):
        captured["dry_run"] = dry_run
        return CanvasSyncReport()

    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(cli, "client_from_settings", lambda: object())
    monkeypatch.setattr(cli, "sync_canvas", fake_sync)

    cli.main(["canvas-sync", "--dry-run"])

    assert captured == {"dry_run": True}
    assert "dry-run" in capsys.readouterr().out


def test_course_and_dry_run_flags_are_passed_through(monkeypatch):
    captured = {}

    def fake_sync(db, course_slug=None, dry_run=False):
        captured["course_slug"] = course_slug
        captured["dry_run"] = dry_run
        return SyncReport()

    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(cli, "sync_corpus", fake_sync)

    cli.main(["sync", "--course", "deep-learning", "--dry-run"])

    assert captured == {"course_slug": "deep-learning", "dry_run": True}
