"""Het leesmodel van de agenda: status, bucket, verschillen met course.yml,
doorlinks en de copilot-toestand per vak. Alles met een vaste `now`."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.models import (
    CanvasAnnouncement,
    CanvasCourse,
    CanvasFile,
    CanvasItem,
    Course,
    Document,
    PracticeCard,
    Task,
    WeekSummary,
)
from app.services.canvas.agenda import build_agenda, bucket_for, derive_status, local_date, normalize_name, place_for

# Donderdag 17 september 2026, 10:00 in Amsterdam (zomertijd: UTC+2).
NOW = datetime(2026, 9, 17, 8, 0)
FDS = 59831
SSO = 59863


def _item(**overrides) -> CanvasItem:
    values = dict(
        id="assignment:1", canvas_course_id=FDS, kind="assignment", title="Assignment 1",
        submission={}, submission_types=["online_upload"], marked_complete=False, done_at=None,
        due_at=NOW + timedelta(days=5), unlock_at=None, lock_at=None,
    )
    values.update(overrides)
    return CanvasItem(**values)


# --- status --------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"submission": {"workflow_state": "graded", "submitted_at": "x", "score": 8.5}}, "graded"),
        ({"submission": {"workflow_state": "submitted", "submitted_at": "x", "late": False}}, "submitted"),
        ({"submission": {"workflow_state": "submitted", "submitted_at": "x", "late": True}}, "late"),
        ({"done_at": NOW}, "done"),
        ({"marked_complete": True}, "done"),
        ({"submission": {"workflow_state": "unsubmitted", "missing": True}}, "missing"),
        ({"lock_at": NOW - timedelta(hours=1), "due_at": NOW - timedelta(days=1)}, "closed"),
        ({"due_at": NOW - timedelta(hours=1)}, "overdue"),
        ({"unlock_at": NOW + timedelta(days=1)}, "locked"),
        ({}, "open"),
    ],
)
def test_status_of_an_assignment(overrides, expected):
    assert derive_status(_item(**overrides), NOW) == expected


def test_a_canvas_checkmark_can_be_undone_here():
    """Het token kan in Canvas niets uitvinken, dus een lokale terugzetting
    moet van marked_complete winnen; anders is het item voorgoed weg."""
    assert derive_status(_item(marked_complete=True), NOW) == "done"
    assert derive_status(_item(marked_complete=True, unmarked_at=NOW), NOW) == "open"
    # Vink je hem hier daarna weer af, dan telt dat gewoon.
    assert derive_status(_item(marked_complete=True, unmarked_at=NOW, done_at=NOW), NOW) == "done"


def test_an_exam_is_upcoming_or_past_never_locked_or_overdue():
    """Het tentamen heeft in Canvas unlock_at == due_at; 'nog niet open' is
    geen zinnige status voor een tentamen."""
    exam = _item(kind="exam", submission_types=["on_paper"], unlock_at=NOW + timedelta(days=30), due_at=NOW + timedelta(days=30))
    assert derive_status(exam, NOW) == "upcoming"
    assert derive_status(_item(kind="exam", due_at=NOW - timedelta(days=1)), NOW) == "past"
    assert derive_status(_item(kind="exam", due_at=NOW - timedelta(days=1), done_at=NOW), NOW) == "done"


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"submission": {"workflow_state": "complete", "score": 13.5, "finished_at": "x"}}, "graded"),
        ({"marked_complete": True}, "done"),
        ({"lock_at": NOW - timedelta(days=1)}, "closed"),
        ({"unlock_at": NOW + timedelta(days=1)}, "locked"),
        ({}, "open"),
    ],
)
def test_status_of_a_quiz(overrides, expected):
    quiz = _item(id="quiz:1", kind="quiz", submission_types=[], due_at=None, lock_at=NOW + timedelta(days=10))
    for key, value in overrides.items():
        setattr(quiz, key, value)
    assert derive_status(quiz, NOW) == expected


def test_status_of_an_event():
    assert derive_status(_item(kind="event", due_at=NOW + timedelta(hours=2), lock_at=NOW + timedelta(hours=3)), NOW) == "upcoming"
    assert derive_status(_item(kind="event", due_at=NOW - timedelta(hours=2), lock_at=NOW - timedelta(hours=1)), NOW) == "past"


# --- bucket --------------------------------------------------------------------


def test_local_date_is_the_amsterdam_calendar_day():
    assert local_date(datetime(2026, 9, 17, 22, 30)) == date(2026, 9, 18)
    assert local_date(datetime(2026, 9, 17, 21, 59)) == date(2026, 9, 17)


@pytest.mark.parametrize(
    "deadline, expected",
    [
        (datetime(2026, 9, 17, 7, 0), "overdue"),      # 09:00 lokaal, een uur geleden
        (datetime(2026, 9, 17, 21, 59), "today"),      # 23:59 lokaal
        (datetime(2026, 9, 17, 22, 30), "tomorrow"),   # 00:30 lokaal op de 18e
        (datetime(2026, 9, 20, 10, 0), "this_week"),   # zondag
        (datetime(2026, 9, 21, 10, 0), "next_week"),   # maandag
        (datetime(2026, 9, 28, 21, 59), "later"),
        (date(2026, 9, 16), "overdue"),
        (date(2026, 9, 17), "today"),
        (date(2026, 10, 21), "later"),
        (None, "undated"),
    ],
)
def test_bucket_boundaries_follow_amsterdam_time(deadline, expected):
    assert bucket_for(deadline, now=NOW, finished=False) == expected


def test_finished_things_land_in_done_whatever_the_date():
    assert bucket_for(datetime(2026, 9, 10, 0, 0), now=NOW, finished=True) == "done"
    assert bucket_for(None, now=NOW, finished=True) == "done"


@pytest.mark.parametrize(
    "deadline, expected",
    [
        (date(2026, 9, 17), "today"),
        (date(2026, 9, 18), "tomorrow"),
        (date(2026, 9, 22), "next_week"),
        # De deadline van vanochtend is verstreken, maar de dag niet: een
        # opdracht die je om 9 uur inleverde hoort vandaag bij vandaag.
        (datetime(2026, 9, 17, 7, 0), "today"),
        (None, "undated"),
        # Is de dag voorbij, dan staat hij een week bij Verlopen, met vinkje,
        # tussen de rest van de afgelopen dagen; pas daarna bij Afgerond.
        (date(2026, 9, 16), "overdue"),
        (datetime(2026, 9, 10, 0, 0), "overdue"),
        (date(2026, 9, 9), "done"),
    ],
)
def test_a_finished_row_keeps_its_day_until_the_day_is_over(deadline, expected):
    """Afvinken verplaatste een rij na tien seconden naar een ingeklapte strip:
    voor wie het deed was hij weg, en daarmee ook wat je gedaan had."""
    assert place_for(deadline, now=NOW, finished=True) == expected


@pytest.mark.parametrize(
    "finished_on, expected",
    [
        (date(2026, 9, 17), "overdue"),  # vandaag afgevinkt: blijft bij Verlopen, met vinkje
        (date(2026, 9, 16), "overdue"),  # gisteren afgevinkt: ook nog bij Verlopen
        (None, "overdue"),
    ],
)
def test_a_late_row_ticked_today_stays_where_you_ticked_it(finished_on, expected):
    """Wie vandaag de taak van gisteren afvinkt, zag hem eerst meteen
    verspringen. Hij blijft de rest van de dag staan waar hij stond."""
    assert place_for(date(2026, 9, 16), now=NOW, finished=True, finished_on=finished_on) == expected


def test_what_you_did_last_week_stays_in_sight():
    """De taken van dinsdag stonden donderdag onderaan de pagina, onder alles
    van volgende week: weg dus. Een apart blok Gedaan zag je ook niet: ze horen
    bij Verlopen, onder elkaar met de rest. Een week lang. Telt de dag
    van het vinkje of de dag van de taak? De laatste van de twee: wie gisteren
    een oude taak afvinkte, heeft hem gisteren gedaan."""
    assert place_for(date(2026, 9, 15), now=NOW, finished=True, finished_on=date(2026, 9, 16)) == "overdue"
    assert place_for(date(2026, 9, 1), now=NOW, finished=True, finished_on=date(2026, 9, 16)) == "overdue"
    assert place_for(date(2026, 9, 1), now=NOW, finished=True, finished_on=date(2026, 9, 2)) == "done"


def test_an_open_row_stands_where_its_bucket_says():
    for deadline in (datetime(2026, 9, 17, 7, 0), date(2026, 9, 18), date(2026, 10, 21), None):
        assert place_for(deadline, now=NOW, finished=False) == bucket_for(deadline, now=NOW, finished=False)


def test_normalize_name_ignores_case_and_punctuation():
    assert normalize_name(" Assignment 1 ") == normalize_name("assignment-1") == "assignment 1"


# --- build_agenda ------------------------------------------------------------


def _fds(db):
    db.add(
        Course(
            slug="fundamentals-of-ds", name="Fundamentals of DS", canvas_id=FDS,
            deadlines={"4": "2026-09-28", "6": "2026-10-12"},
            assignments=[
                {"name": "Assignment 1", "week": 4, "due_date": "2026-09-28", "available_date": "2026-09-11", "points": 100.0},
                {"name": "Assignment 2", "week": 6, "due_date": "2026-10-13", "available_date": None, "points": 100.0},
            ],
            exams=[{"name": "Tentamen", "date": "2026-10-21"}, {"name": "Herkansing", "date": "2026-12-14"}],
            week_plans={"1": {"lectures": [], "topics": [], "reading": []}, "2": {"lectures": [], "topics": [], "reading": []}},
        )
    )
    db.add(CanvasCourse(id=FDS, name="Fundamentals of Data Science", course_code="5294FUDS6Y", term="2026/27", fetched_at=NOW - timedelta(minutes=5)))
    db.add_all(
        [
            _item(id="assignment:714239", title="Assignment 1", due_at=datetime(2026, 9, 28, 21, 59), points_possible=100.0,
                  html_url="https://canvas.test/a/714239", description="Zie het opgavenblad."),
            _item(id="assignment:714240", title="Assignment 2", due_at=datetime(2026, 10, 12, 21, 59), points_possible=100.0),
            _item(id="assignment:714241", title="Final Exam", kind="exam", submission_types=["on_paper"],
                  due_at=datetime(2026, 10, 21, 7, 30), unlock_at=datetime(2026, 10, 21, 7, 30)),
            _item(id="quiz:135546", title="Quiz 1", kind="quiz", submission_types=[], due_at=None,
                  unlock_at=datetime(2026, 9, 11, 11, 0), lock_at=datetime(2026, 10, 21, 17, 0),
                  answers_at=datetime(2026, 9, 14, 7, 0), points_possible=15.0,
                  submission={"workflow_state": "complete", "score": 13.5, "attempt": 1, "finished_at": "2026-09-11T12:29:00Z"}),
            _item(id="event:55", title="Office hours", kind="event", submission_types=[],
                  due_at=NOW + timedelta(hours=3), lock_at=NOW + timedelta(hours=4)),
        ]
    )
    db.add(CanvasAnnouncement(id=1, canvas_course_id=FDS, title="Week 3 announcements", posted_at=NOW - timedelta(days=3), body="De slides staan hier.", read_state="unread"))
    db.add(CanvasAnnouncement(id=2, canvas_course_id=FDS, title="Week 2 announcements", posted_at=NOW - timedelta(days=10), body="Welkom.", read_state="read"))
    db.add(CanvasFile(id=9001, canvas_course_id=FDS, filename="FDS_assignment1.pdf", display_name="FDS_assignment1.pdf",
                      source="assignment:Assignment 1", assignment_item_id="assignment:714239"))
    db.add(Document(title="Opgavenblad 1", source_path="fundamentals-of-ds/assignments/week-04/a1.pdf", checksum="x",
                    course_slug="fundamentals-of-ds", doc_kind="assignment", week=4, assignment_status="open", ingestion_status="indexed"))
    db.add(PracticeCard(course_slug="fundamentals-of-ds", document_id="doc", chunk_id="chunk", section_path="PDSH › Ch 2",
                        page_start=1, page_end=1, kind="code", setup="x = 1", question="?", reference_answer="x"))
    db.add(WeekSummary(course_slug="fundamentals-of-ds", week=1, content={"thread": "…"}, source_fingerprint="f", chunks_used=1, chunks_total=1))
    db.commit()


def test_items_carry_status_bucket_and_the_course_they_belong_to(db_session):
    _fds(db_session)

    agenda = build_agenda(db_session, now=NOW)

    by_id = {item.id: item for item in agenda.items}
    a1 = by_id["assignment:714239"]
    assert a1.course_slug == "fundamentals-of-ds" and a1.course_name == "Fundamentals of Data Science"
    assert a1.status == "open" and a1.bucket == "later" and a1.days_left == 11
    assert a1.deadline_at == datetime(2026, 9, 28, 21, 59).replace(tzinfo=a1.deadline_at.tzinfo)
    assert by_id["quiz:135546"].status == "graded" and by_id["quiz:135546"].bucket == "done"
    assert by_id["quiz:135546"].score == 13.5 and by_id["quiz:135546"].deadline_at is not None
    assert by_id["quiz:135546"].quiz.answers_at is not None
    assert by_id["event:55"].bucket == "today" and by_id["event:55"].status == "upcoming"
    assert [item.id for item in agenda.items][:2] == ["event:55", "assignment:714239"]


def test_the_server_says_which_items_can_be_ticked(db_session):
    """De frontend hoeft niet op het id-schema te sniffen of de statuslijst te
    kopieren: af te vinken is wat een rij heeft en nog niet vastligt."""
    _fds(db_session)

    agenda = build_agenda(db_session, now=NOW)

    by_id = {item.id: item for item in agenda.items}
    assert by_id["assignment:714239"].tickable is True
    assert by_id["event:55"].tickable is True
    # Beoordeeld: het vinkje heeft geen betekenis meer.
    assert by_id["quiz:135546"].tickable is False
    # Een tentamen uit course.yml heeft geen CanvasItem-rij om te patchen.
    yaml_exams = [item for item in agenda.items if item.id.startswith("exam:")]
    assert yaml_exams and all(item.tickable is False for item in yaml_exams)


def test_yaml_link_and_coach_document_come_from_course_yml(db_session):
    _fds(db_session)

    agenda = build_agenda(db_session, now=NOW)

    by_id = {item.id: item for item in agenda.items}
    assert by_id["assignment:714239"].yaml.week == 4
    assert by_id["assignment:714239"].yaml.same_day is True
    assert by_id["assignment:714239"].coach_document_id is not None
    # Assignment 2: course.yml zegt 13 oktober, Canvas 12 oktober.
    assert by_id["assignment:714240"].yaml.same_day is False
    assert by_id["assignment:714240"].coach_document_id is None


def test_differences_with_course_yml_are_reported_never_applied(db_session):
    _fds(db_session)

    agenda = build_agenda(db_session, now=NOW)

    course = next(entry for entry in agenda.courses if entry.canvas_id == FDS)
    kinds = {diff.kind for diff in course.diffs}
    assert "due_date_differs" in kinds
    differs = next(diff for diff in course.diffs if diff.kind == "due_date_differs")
    assert "Assignment 2" in differs.message and "2026-10-13" in differs.message and "2026-10-12" in differs.message
    assert differs.item_id == "assignment:714240"
    sheet = next(diff for diff in course.diffs if diff.kind == "assignment_sheet_missing")
    assert sheet.week == 6
    assert db_session.get(Course, "fundamentals-of-ds").deadlines == {"4": "2026-09-28", "6": "2026-10-12"}


def test_exams_merge_course_yml_and_canvas(db_session):
    _fds(db_session)

    agenda = build_agenda(db_session, now=NOW)

    course = next(entry for entry in agenda.courses if entry.canvas_id == FDS)
    exams = {exam.name: exam for exam in course.exams}
    assert exams["Tentamen"].source == "both" and exams["Tentamen"].canvas_item_id == "assignment:714241"
    assert exams["Tentamen"].days_left == 34
    assert exams["Herkansing"].source == "yaml"
    # De herkansing staat niet in Canvas: hij komt als eigen item in de lijst.
    herkansing = next(item for item in agenda.items if item.kind == "exam" and item.title == "Herkansing")
    assert herkansing.due_on == date(2026, 12, 14) and herkansing.bucket == "later"


def test_copilot_state_per_course(db_session):
    _fds(db_session)

    agenda = build_agenda(db_session, now=NOW)

    course = next(entry for entry in agenda.courses if entry.canvas_id == FDS)
    assert course.copilot.due_count == 1
    assert course.copilot.weeks_without_summary == [2]
    assert course.copilot.exam_sets == []
    # Vijf Canvas-items plus de herkansing uit course.yml.
    assert course.item_count == 6
    assert [a.title for a in course.announcements] == ["Week 3 announcements", "Week 2 announcements"]
    assert course.announcements[0].unread is True


def test_a_summary_older_than_its_material_is_flagged(db_session):
    """Nieuwe colleges of opgaven in een week maken de weekkaart verouderd; de
    agenda is waar je dat ziet voordat je hem gaat leren."""
    from app.services.weeks_summary import week_material

    _fds(db_session)
    fingerprint = week_material(db_session, "fundamentals-of-ds", 2).fingerprint
    db_session.add(WeekSummary(course_slug="fundamentals-of-ds", week=2, content={"thread": "…"},
                               source_fingerprint=fingerprint, chunks_used=0, chunks_total=0))
    db_session.commit()

    course = next(entry for entry in build_agenda(db_session, now=NOW).courses if entry.canvas_id == FDS)

    # Week 1 draagt vingerafdruk "f", die niet bij de stof hoort; week 2 klopt.
    assert course.copilot.stale_summaries == [1]
    assert course.copilot.weeks_without_summary == []


def test_a_hidden_course_keeps_its_items_out_of_the_list(db_session):
    _fds(db_session)
    db_session.get(CanvasCourse, FDS).hidden = True
    db_session.commit()

    agenda = build_agenda(db_session, now=NOW)

    assert [item for item in agenda.items if item.course_id == FDS] == []
    assert next(entry for entry in agenda.courses if entry.canvas_id == FDS).hidden is True


def test_a_hidden_course_takes_your_own_tasks_along(db_session):
    """Een vak dat je verbergt doe je niet meer: ook je studietaken ervoor
    horen dan niet meer onder Verlopen of Binnenkort."""
    _fds(db_session)
    db_session.get(CanvasCourse, FDS).hidden = True
    db_session.add_all(
        [
            Task(id="fds-open", title="Oefententamen 3", due_on=date(2026, 9, 16), course_slug="fundamentals-of-ds"),
            Task(id="fds-af", title="Weekkaart 2", due_on=date(2026, 9, 14), course_slug="fundamentals-of-ds", done_at=NOW),
            Task(id="los", title="Fietsband plakken", due_on=date(2026, 9, 17)),
        ]
    )
    db_session.commit()

    agenda = build_agenda(db_session, now=NOW)

    assert [task.id for task in agenda.tasks] == ["los"]


def test_a_corpus_course_without_canvas_id_is_listed_with_a_hint(db_session):
    db_session.add(Course(slug="deep-learning", name="Deep Learning"))
    db_session.commit()

    agenda = build_agenda(db_session, now=NOW)

    course = next(entry for entry in agenda.courses if entry.course_slug == "deep-learning")
    assert course.canvas_id is None
    assert [diff.kind for diff in course.diffs] == ["canvas_id_missing"]


def test_an_unmapped_canvas_course_shows_deadlines_only(db_session):
    db_session.add(CanvasCourse(id=59837, name="Data Systems Project", course_code="5294DASP6Y", fetched_at=NOW))
    db_session.add(_item(id="assignment:9", canvas_course_id=59837, title="Deliverable 1", due_at=datetime(2026, 10, 21, 21, 59)))
    db_session.commit()

    agenda = build_agenda(db_session, now=NOW)

    course = next(entry for entry in agenda.courses if entry.canvas_id == 59837)
    assert course.course_slug is None and course.copilot is None and course.diffs == []
    assert agenda.items[0].course_slug is None and agenda.items[0].coach_document_id is None


def test_tasks_are_bucketed_and_open_ones_come_first(db_session):
    db_session.add_all(
        [
            Task(id="t1", title="Sectie 3 maken", due_on=date(2026, 9, 17)),
            Task(id="t2", title="Herhalen", due_on=None),
            Task(id="t3", title="Gedaan", due_on=date(2026, 9, 10), done_at=NOW),
            Task(id="t4", title="Eerder", due_on=date(2026, 9, 16), course_slug="sso"),
            # Zacht verwijderd: de rij blijft staan om terug te halen, maar
            # hoort in geen enkele bak thuis.
            Task(id="t5", title="Weg", due_on=date(2026, 9, 17), deleted_at=NOW),
        ]
    )
    db_session.commit()

    agenda = build_agenda(db_session, now=NOW)

    assert [task.id for task in agenda.tasks] == ["t4", "t1", "t2", "t3"]
    assert {task.id: task.bucket for task in agenda.tasks} == {"t4": "overdue", "t1": "today", "t2": "undated", "t3": "done"}


def test_stale_follows_the_last_fetch(db_session):
    agenda = build_agenda(db_session, now=NOW)
    assert agenda.canvas.synced_at is None and agenda.canvas.stale is True and agenda.canvas.configured is False

    db_session.add(CanvasCourse(id=FDS, name="FDS", fetched_at=NOW - timedelta(minutes=10)))
    db_session.commit()
    assert build_agenda(db_session, now=NOW).canvas.stale is False

    db_session.get(CanvasCourse, FDS).fetched_at = NOW - timedelta(minutes=31)
    db_session.commit()
    assert build_agenda(db_session, now=NOW).canvas.stale is True


def test_times_go_over_the_wire_as_utc_with_a_z(db_session):
    """Opslag is naïef; zonder tijdzone leest de browser 21:59 als lokale
    tijd, twee uur ernaast."""
    _fds(db_session)

    payload = build_agenda(db_session, now=NOW).model_dump(mode="json")

    item = next(entry for entry in payload["items"] if entry["id"] == "assignment:714239")
    assert item["due_at"] == "2026-09-28T21:59:00Z"
    assert payload["now"].endswith("Z")
