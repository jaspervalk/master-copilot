from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import cli
from app.core.config import settings
from app.schemas import AgendaItemRead, TaskRead
from app.services.canvas import notify
from app.services.canvas.agenda import bucket_for
from app.services.canvas.client import CanvasError

TODAY = date(2026, 11, 9)
SECRET_TOPIC = "geheim-topic-123"


def _item(
    title: str,
    days_left: int | None,
    *,
    status: str = "open",
    kind: str = "assignment",
    bucket: str = "later",
) -> AgendaItemRead:
    return AgendaItemRead(
        id=title, kind=kind, course_id=1, course_slug="dsp", course_name="DSP",
        title=title, days_left=days_left, status=status, bucket=bucket, place=bucket,
    )


def _task(title: str, due_on: date | None, *, bucket: str = "later") -> TaskRead:
    return TaskRead(
        id=title, title=title, notes="", due_on=due_on, course_slug=None, link=None,
        done_at=None, created_at=datetime(2026, 11, 1, tzinfo=timezone.utc), bucket=bucket, place=bucket,
    )


def _due(days_left: int = 2, label: str = "DSP - verslag") -> notify.Due:
    return notify.Due(days_left=days_left, label=label)


class _Recorder:
    """Een opener die het verzoek bewaart: geen test raakt het netwerk."""

    def __init__(self, *failures: Exception) -> None:
        self.requests: list[urllib.request.Request] = []
        self.failures = list(failures)

    def __call__(self, request: urllib.request.Request, timeout: int | None = None):
        self.requests.append(request)
        if self.failures:
            raise self.failures.pop(0)
        return SimpleNamespace(close=lambda: None)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(f"https://ntfy.test/{SECRET_TOPIC}", code, "fout", None, None)


# --- wat er in het bericht komt ---------------------------------------------


def test_due_soon_keeps_open_items_within_the_window_sorted():
    items = [
        _item("ver weg", 5),
        _item("over twee", 2),
        _item("vandaag", 0, bucket="today"),
        _item("ingeleverd", 1, status="submitted", bucket="done"),
        _item("gisteren", -1, status="overdue", bucket="overdue"),
        _item("zonder datum", None, bucket="undated"),
    ]

    due = notify.due_soon(items, [], days=3, today=TODAY)

    assert [d.label for d in due] == ["DSP - vandaag", "DSP - over twee"]


def test_a_calendar_event_is_not_a_deadline():
    """Een college morgen gaf anders elke dag een melding met hoge prioriteit,
    en dan zie je de echte deadline niet meer staan."""
    items = [
        _item("College 5", 1, status="upcoming", kind="event", bucket="tomorrow"),
        _item("Tentamen", 1, status="upcoming", kind="exam", bucket="tomorrow"),
    ]

    assert [d.label for d in notify.due_soon(items, [], days=3, today=TODAY)] == ["DSP - Tentamen"]


def test_a_deadline_that_passed_earlier_today_is_not_due():
    """Vandaag om 00:00 afgelopen, om 08:00 gemeld: `days_left` is dan nog 0,
    dus de kalenderdag alleen zegt niet dat er nog tijd is."""
    now = datetime(2026, 11, 9, 7, 0)
    bucket = bucket_for(datetime(2026, 11, 8, 23, 0), now=now, finished=False)
    items = [_item("al voorbij", 0, status="overdue", bucket=bucket)]

    assert notify.due_soon(items, [], days=3, today=TODAY) == []


def test_open_tasks_with_a_date_count_as_well():
    tasks = [
        _task("hoofdstuk 5 lezen", TODAY + timedelta(days=1), bucket="tomorrow"),
        _task("ver weg", TODAY + timedelta(days=9)),
        _task("zonder datum", None, bucket="undated"),
        _task("afgevinkt", TODAY, bucket="done"),
        _task("gisteren vergeten", TODAY - timedelta(days=1), bucket="overdue"),
    ]
    items = [_item("verslag", 0, bucket="today"), _item("quiz", 2)]

    due = notify.due_soon(items, tasks, days=3, today=TODAY)

    assert [d.label for d in due] == ["DSP - verslag", "hoofdstuk 5 lezen", "DSP - quiz"]


def test_the_message_is_in_dutch():
    due = [_due(0, "a"), _due(1, "b"), _due(2, "c")]

    assert notify.message(due) == "vandaag: a\nmorgen: b\nover 2 dagen: c"


# --- versturen --------------------------------------------------------------


def test_send_posts_the_message_to_the_topic():
    opener = _Recorder()

    notify.send("https://ntfy.test/", SECRET_TOPIC, [_due(2, "a"), _due(3, "b")], opener=opener)

    request = opener.requests[0]
    assert request.full_url == f"https://ntfy.test/{SECRET_TOPIC}"
    assert request.get_method() == "POST"
    assert request.data == "over 2 dagen: a\nover 3 dagen: b".encode()
    assert request.get_header("Title") == "2 deadlines binnenkort"
    assert request.get_header("Priority") == "default"


def test_one_deadline_is_singular_in_the_title():
    opener = _Recorder()

    notify.send("https://ntfy.test", SECRET_TOPIC, [_due(2)], opener=opener)

    assert opener.requests[0].get_header("Title") == "1 deadline binnenkort"


@pytest.mark.parametrize("days_left", [0, 1])
def test_today_or_tomorrow_is_high_priority(days_left):
    opener = _Recorder()

    notify.send("https://ntfy.test", SECRET_TOPIC, [_due(days_left), _due(3)], opener=opener)

    assert opener.requests[0].get_header("Priority") == "high"


def test_send_uses_the_certificates_of_the_canvas_client(monkeypatch):
    """De python.org-build op macOS heeft geen CA-bundel. Met de standaardcontext
    faalde elke melding op CERTIFICATE_VERIFY_FAILED, terwijl Canvas gewoon werkte."""
    seen: dict = {}

    def urlopen(request, timeout=None, context=None):
        seen["context"] = context
        return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    notify.send("https://ntfy.test", SECRET_TOPIC, [_due()])

    assert isinstance(seen["context"], ssl.SSLContext)


def test_a_network_failure_is_tried_again():
    """Een Mac die net wakker is heeft nog geen wifi, en launchd probeert het pas
    de volgende ochtend opnieuw."""
    opener = _Recorder(urllib.error.URLError("no network"), TimeoutError("timed out"))
    pauses: list[float] = []

    notify.send("https://ntfy.test", SECRET_TOPIC, [_due()], opener=opener, sleep=pauses.append)

    assert len(opener.requests) == 3
    assert len(pauses) == 2


@pytest.mark.parametrize("code", [429, 503])
def test_a_temporary_refusal_is_tried_again(code):
    opener = _Recorder(_http_error(code))

    notify.send("https://ntfy.test", SECRET_TOPIC, [_due()], opener=opener, sleep=lambda _: None)

    assert len(opener.requests) == 2


def test_a_permanent_refusal_is_not_tried_again():
    opener = _Recorder(_http_error(403))

    with pytest.raises(notify.NotifyError) as caught:
        notify.send("https://ntfy.test", SECRET_TOPIC, [_due()], opener=opener, sleep=lambda _: None)

    assert len(opener.requests) == 1
    assert "403" in str(caught.value)


def test_a_failure_never_names_the_topic():
    """Het topic is het geheim, en een HTTPError draagt de hele URL."""
    opener = _Recorder(_http_error(500), _http_error(500), _http_error(500))

    with pytest.raises(notify.NotifyError) as caught:
        notify.send("https://ntfy.test", SECRET_TOPIC, [_due()], opener=opener, sleep=lambda _: None)

    assert len(opener.requests) == 3
    assert SECRET_TOPIC not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_giving_up_names_the_network_cause():
    failures = [urllib.error.URLError("no network") for _ in range(3)]

    with pytest.raises(notify.NotifyError, match="no network"):
        notify.send("https://ntfy.test", SECRET_TOPIC, [_due()], opener=_Recorder(*failures), sleep=lambda _: None)


# --- het commando -----------------------------------------------------------


class _FakeSession:
    def close(self) -> None:
        pass


@pytest.fixture()
def agenda(monkeypatch) -> SimpleNamespace:
    """`cli notify` zonder database, Canvas of netwerk: wat de test hierin zet is
    de agenda, en `sent` is wat er verstuurd is."""
    state = SimpleNamespace(items=[], tasks=[], sent=[])
    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(cli, "client_from_settings", lambda: None)
    monkeypatch.setattr("app.services.canvas.agenda.build_agenda", lambda db: state)
    monkeypatch.setattr(notify, "send", lambda server, topic, due: state.sent.append(due))
    return state


def test_without_a_topic_the_command_says_what_to_set(agenda, capsys):
    agenda.items = [_item("verslag", 0, bucket="today")]

    assert cli.main(["notify"]) == 1
    assert "NTFY_TOPIC" in capsys.readouterr().out
    assert agenda.sent == []


def test_a_dry_run_shows_the_message_and_sends_nothing(agenda, capsys):
    agenda.items = [_item("verslag", 0, bucket="today")]

    assert cli.main(["notify", "--dry-run"]) == 0
    assert "vandaag: DSP - verslag" in capsys.readouterr().out
    assert agenda.sent == []


def test_nothing_due_sends_nothing(agenda, monkeypatch, capsys):
    monkeypatch.setattr(settings, "ntfy_topic", SECRET_TOPIC)
    agenda.items = [_item("ver weg", 9)]

    assert cli.main(["notify"]) == 0
    assert agenda.sent == []
    assert "Niets binnen 3 dagen" in capsys.readouterr().out


def test_tasks_reach_the_phone(agenda, monkeypatch):
    monkeypatch.setattr(settings, "ntfy_topic", SECRET_TOPIC)
    # Morgen in UTC is vandaag of morgen in Amsterdam; allebei binnen het venster.
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    agenda.tasks = [_task("hoofdstuk 5 lezen", tomorrow, bucket="tomorrow")]

    assert cli.main(["notify"]) == 0
    assert [d.label for d in agenda.sent[0]] == ["hoofdstuk 5 lezen"]


def test_a_canvas_failure_falls_back_on_the_last_snapshot(agenda, monkeypatch, capsys):
    monkeypatch.setattr(settings, "ntfy_topic", SECRET_TOPIC)
    monkeypatch.setattr(cli, "client_from_settings", lambda: object())

    def broken(db, client):
        raise CanvasError(None, "courses", "timed out")

    monkeypatch.setattr(cli, "sync_canvas", broken)
    agenda.items = [_item("verslag", 0, bucket="today")]

    assert cli.main(["notify"]) == 0
    assert len(agenda.sent) == 1
    assert "oude gegevens" in capsys.readouterr().out


def test_a_failed_send_ends_readably_without_the_topic(agenda, monkeypatch, capsys):
    monkeypatch.setattr(settings, "ntfy_topic", SECRET_TOPIC)
    agenda.items = [_item("verslag", 0, bucket="today")]

    def broken(server, topic, due):
        raise notify.NotifyError("ntfy onbereikbaar: no network")

    monkeypatch.setattr(notify, "send", broken)

    assert cli.main(["notify"]) == 1
    output = capsys.readouterr().out
    assert "ntfy onbereikbaar" in output
    assert SECRET_TOPIC not in output


def test_no_test_can_reach_a_real_topic():
    """De echte .env heeft na het aanzetten een topic; dan gaat een test die
    `cli notify` aanroept anders echt naar je telefoon."""
    assert settings.ntfy_topic is None
