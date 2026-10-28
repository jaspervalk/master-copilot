from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.models import CanvasAnnouncement, CanvasCourse, CanvasFile, CanvasItem, CanvasPage, Course, Document
from app.services.canvas.client import CanvasClient, CanvasError
from app.services.canvas.sync import sync_canvas
from tests.canvas_fixtures import FDS, OLD, SSO, course_yml, routes
from tests.canvas_stub import canvas_opener

NOW = datetime(2026, 9, 17, 10, 0)


def _client(fixture: dict) -> tuple[CanvasClient, object]:
    stub = canvas_opener(fixture)
    return CanvasClient(base_url="https://canvas.test", token="test-token", opener=stub), stub


def _corpus(tmp_corpus, *, sso_due: str = "2026-09-28"):
    """Twee vakken met een course.yml; het oude vak (6056) heeft er geen."""
    (tmp_corpus / "fundamentals-of-ds").mkdir()
    (tmp_corpus / "fundamentals-of-ds" / "course.yml").write_text(course_yml(FDS), encoding="utf-8")
    (tmp_corpus / "sso").mkdir()
    (tmp_corpus / "sso" / "course.yml").write_text(course_yml(SSO, assignment_due=sso_due), encoding="utf-8")


def _sync(db_session, tmp_corpus, fixture: dict | None = None, **kwargs):
    client, stub = _client(fixture or routes())
    report = sync_canvas(db_session, client, now=NOW, corpus_root=tmp_corpus, **kwargs)
    return report, stub


def test_first_sync_mirrors_courses_items_and_announcements(tmp_corpus, db_session):
    _corpus(tmp_corpus)

    report, _ = _sync(db_session, tmp_corpus)

    assert {course.id for course in db_session.scalars(select(CanvasCourse))} == {FDS, SSO, OLD}
    items = {item.id: item for item in db_session.scalars(select(CanvasItem))}
    assert items["assignment:714239"].kind == "assignment"
    assert items["assignment:714239"].due_at == datetime(2026, 9, 28, 21, 59)
    assert items["assignment:714239"].description == "Zie het opgavenblad."
    # `on_paper` is een tentamen; "Retake exam" heeft types ["none"] en telt op naam.
    assert items["assignment:714241"].kind == "exam"
    assert items["assignment:714243"].kind == "exam"
    assert items["assignment:704507"].submission["score"] == 8.5
    assert items["assignment:704507"].submission["workflow_state"] == "graded"
    assert items["quiz:135546"].kind == "quiz"
    assert items["quiz:135546"].lock_at == datetime(2026, 10, 21, 17, 0)
    assert items["quiz:135546"].answers_at == datetime(2026, 9, 14, 7, 0)
    assert items["quiz:135546"].submission["score"] == 13.5
    assert items["quiz:135546"].marked_complete is True
    assert items["quiz:135544"].submission == {}
    assert items["event:55"].kind == "event"
    assert items["event:55"].due_at == datetime(2026, 9, 16, 8, 0)
    assert items["event:55"].lock_at == datetime(2026, 9, 16, 9, 0)
    assert "announcement:1159317" not in items and "discussion:77" not in items

    announcements = {row.id: row for row in db_session.scalars(select(CanvasAnnouncement))}
    assert announcements[1159317].read_state == "unread"
    assert announcements[1159317].body == "De slides staan hier."
    assert report.courses == 3 and report.items == 8 and report.announcements == 3
    assert db_session.get(CanvasCourse, FDS).fetched_at == NOW


def test_files_are_harvested_from_modules_pages_descriptions_and_announcements(tmp_corpus, db_session):
    _corpus(tmp_corpus)

    report, _ = _sync(db_session, tmp_corpus)

    files = {row.id: row for row in db_session.scalars(select(CanvasFile))}
    assert set(files) == {9001, 9002, 9003, 9004, 9005}
    assert files[9003].source == "module:Week 3"
    assert files[9003].module_name == "Week 3"
    assert files[9003].folder == "Lectures slides"
    assert files[9001].source == "assignment:Assignment 1"
    assert files[9001].assignment_item_id == "assignment:714239"
    assert files[9002].source == "announcement:Week 3 announcements"
    assert files[9004].source == "page:Schedule for the statistics part"
    assert files[9004].folder == "statistics/Slides 2026/Lecture 4"
    assert files[9005].folder == "statistics/Exercises"
    assert files[9005].canvas_course_id == SSO
    assert files[9003].updated_at == datetime(2026, 9, 15, 7, 0)
    assert report.files_seen == 5 and report.files_new == 5


def test_the_download_url_is_never_stored(tmp_corpus, db_session):
    """Die URL draagt een verifier-geheim en verloopt; bij ophalen wordt
    files/{id} opnieuw gelezen."""
    _corpus(tmp_corpus)

    _sync(db_session, tmp_corpus)

    for row in db_session.scalars(select(CanvasFile)):
        assert "verifier" not in " ".join(str(value) for value in vars(row).values())


def test_second_sync_changes_nothing_and_skips_known_files(tmp_corpus, db_session):
    _corpus(tmp_corpus)
    _sync(db_session, tmp_corpus)

    report, stub = _sync(db_session, tmp_corpus)

    assert len(db_session.scalars(select(CanvasItem)).all()) == 8
    assert len(db_session.scalars(select(CanvasFile)).all()) == 5
    assert not [path for path in stub.paths() if path.startswith("files/")]
    assert report.files_new == 0 and report.files_seen == 5


def test_a_vanished_item_disappears_but_what_the_user_set_survives(tmp_corpus, db_session):
    _corpus(tmp_corpus)
    _sync(db_session, tmp_corpus)
    db_session.get(CanvasItem, "assignment:714239").done_at = NOW
    db_session.get(CanvasCourse, OLD).hidden = True
    db_session.get(CanvasFile, 9002).ignored_at = NOW
    db_session.commit()
    fixture = routes()
    fixture[f"courses/{FDS}/assignments"] = [a for a in fixture[f"courses/{FDS}/assignments"] if a["id"] != 714243]

    report, _ = _sync(db_session, tmp_corpus, fixture)

    assert db_session.get(CanvasItem, "assignment:714243") is None
    assert db_session.get(CanvasItem, "assignment:714239").done_at == NOW
    assert db_session.get(CanvasCourse, OLD).hidden is True
    assert db_session.get(CanvasFile, 9002).ignored_at == NOW
    assert report.removed == 1


def test_a_local_untick_survives_a_sync_until_canvas_ticks_again(tmp_corpus, db_session):
    """`unmarked_at` is van de gebruiker en blijft dus staan. Maar zet je het
    vinkje in Canvas opnieuw, dan spreekt Canvas opnieuw en vervalt hij."""
    _corpus(tmp_corpus)
    _sync(db_session, tmp_corpus)
    item = db_session.get(CanvasItem, "assignment:714239")
    item.marked_complete = True
    item.unmarked_at = NOW
    db_session.commit()

    _sync(db_session, tmp_corpus)

    # Canvas zegt nog steeds niet-afgevinkt: de terugzetting blijft.
    assert db_session.get(CanvasItem, "assignment:714239").unmarked_at == NOW

    fixture = routes()
    for entry in fixture["planner/items"]:
        if entry.get("plannable_id") == 714239:
            entry["planner_override"] = {"marked_complete": True}
    _sync(db_session, tmp_corpus, fixture)

    row = db_session.get(CanvasItem, "assignment:714239")
    assert row.marked_complete is True and row.unmarked_at is None


def test_a_course_that_was_not_harvested_keeps_its_files_and_flags(tmp_corpus, db_session):
    """Valt `canvas_id` even weg uit course.yml (tikfout, halve bewerking), dan
    wordt er voor dat vak niets geoogst. Dat mag de negeer- en ophaalvlaggen
    niet wissen."""
    _corpus(tmp_corpus)
    _sync(db_session, tmp_corpus)
    db_session.get(CanvasFile, 9005).ignored_at = NOW
    db_session.commit()
    (tmp_corpus / "sso" / "course.yml").write_text("name: SSO\n", encoding="utf-8")

    _sync(db_session, tmp_corpus)

    assert db_session.get(CanvasFile, 9005) is not None
    assert db_session.get(CanvasFile, 9005).ignored_at == NOW


def test_a_hidden_course_is_not_fetched(tmp_corpus, db_session):
    _corpus(tmp_corpus)
    db_session.add(CanvasCourse(id=OLD, name="oud", hidden=True))
    db_session.commit()

    _, stub = _sync(db_session, tmp_corpus)

    assert not [path for path in stub.paths() if path.startswith(f"courses/{OLD}/")]
    assert db_session.get(CanvasCourse, OLD).name == "Master Information Studies"


def test_material_is_only_harvested_for_courses_with_a_corpus(tmp_corpus, db_session):
    """Zonder corpus is er geen plek om een bestand neer te zetten; die
    aanroepen zijn dan alleen maar traag."""
    _corpus(tmp_corpus)

    _, stub = _sync(db_session, tmp_corpus)

    assert f"courses/{OLD}/modules" not in stub.paths()
    assert f"courses/{OLD}/assignments" in stub.paths()


def test_a_forbidden_helper_endpoint_is_skipped_not_fatal(tmp_corpus, db_session):
    _corpus(tmp_corpus)
    fixture = routes()
    fixture[f"courses/{SSO}/folders"] = 403

    report, _ = _sync(db_session, tmp_corpus, fixture)

    assert any("folders" in what for what, _ in report.skipped)
    assert db_session.get(CanvasFile, 9004).folder is None
    assert db_session.get(CanvasItem, "assignment:704507") is not None


def test_a_hard_failure_leaves_the_previous_snapshot_intact(tmp_corpus, db_session):
    _corpus(tmp_corpus)
    _sync(db_session, tmp_corpus)
    fixture = routes()
    fixture[f"courses/{FDS}/assignments"] = 401

    with pytest.raises(CanvasError):
        _sync(db_session, tmp_corpus, fixture)

    assert len(db_session.scalars(select(CanvasItem)).all()) == 8
    assert db_session.get(CanvasCourse, FDS).fetched_at == NOW


def test_course_rows_are_refreshed_and_a_passed_deadline_closes_the_assignment(tmp_corpus, db_session):
    """Een nieuwe canvas_id in course.yml hoort te werken zonder `sync` (dat
    de Qdrant-lock nodig heeft), en de agenda is de plek waar je merkt dat
    een deadline gisteren verstreek."""
    _corpus(tmp_corpus, sso_due="2026-09-16")
    db_session.add(
        Document(
            title="Opgavenblad", source_path="sso/assignments/week-03/a1.pdf", checksum="x",
            course_slug="sso", doc_kind="assignment", week=3, assignment_status="open",
        )
    )
    db_session.commit()

    _sync(db_session, tmp_corpus)

    assert db_session.get(Course, "fundamentals-of-ds").canvas_id == FDS
    assert db_session.get(Course, "sso").canvas_id == SSO
    assert db_session.scalars(select(Document)).one().assignment_status == "closed"


def test_dry_run_counts_but_writes_nothing(tmp_corpus, db_session):
    _corpus(tmp_corpus)

    report, _ = _sync(db_session, tmp_corpus, dry_run=True)

    assert report.items == 8 and report.files_new == 5
    assert db_session.scalars(select(CanvasItem)).all() == []
    assert db_session.scalars(select(CanvasCourse)).all() == []


def test_the_report_reads_like_the_sync_report(tmp_corpus, db_session):
    _corpus(tmp_corpus)
    fixture = routes()
    fixture[f"courses/{SSO}/folders"] = 403

    report, _ = _sync(db_session, tmp_corpus, fixture)

    lines = report.as_lines()
    assert "vakken: 3" in lines
    assert "items: 8" in lines
    assert "aankondigingen: 3" in lines
    assert "nieuw materiaal: 5" in lines
    assert any(line.startswith("overgeslagen") and "folders" in line for line in lines)


def test_module_pages_are_mirrored_without_their_text(tmp_corpus, db_session):
    """Een pagina is stof (de afleiding van de kleinste kwadraten, het rooster
    met huiswerkopgaven). De tekst wordt bij ophalen vers gelezen; de spiegel
    houdt alleen bij wat er is."""
    _corpus(tmp_corpus)

    _sync(db_session, tmp_corpus)

    pages = {page.id: page for page in db_session.scalars(select(CanvasPage))}
    assert set(pages) == {"59831:details-on-deriving", "59863:schedule-for-the-statistics-part"}
    fds = pages["59831:details-on-deriving"]
    assert fds.title == "Details on deriving least squares"
    assert fds.module_name == "Week 3"
    assert fds.page_url == "details-on-deriving"
    assert fds.canvas_course_id == FDS
    assert fds.updated_at == datetime(2026, 9, 12, 10, 0)


def test_a_vanished_page_disappears_but_an_ignored_page_stays_ignored(tmp_corpus, db_session):
    _corpus(tmp_corpus)
    _sync(db_session, tmp_corpus)
    db_session.get(CanvasPage, "59863:schedule-for-the-statistics-part").ignored_at = NOW
    db_session.commit()
    fixture = routes()
    fixture[f"courses/{FDS}/modules"] = [{"id": 1, "name": "Week 3", "items": []}]

    _sync(db_session, tmp_corpus, fixture)

    assert db_session.get(CanvasPage, "59831:details-on-deriving") is None
    assert db_session.get(CanvasPage, "59863:schedule-for-the-statistics-part").ignored_at == NOW
