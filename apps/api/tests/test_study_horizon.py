"""De herhaalafstand krimpt mee met de tijd tot het tentamen.

Cepeda e.a. (2008) vonden dat de beste tussenpoos meebeweegt met hoe lang je
het moet onthouden: ongeveer een tiende tot een vijfde daarvan. De ladder van
35 dagen is gemaakt voor onthouden op de lange duur; met nog vier weken te gaan
zou een kaart die je vandaag goed hebt dan pas ná het tentamen terugkomen.
"""
from datetime import datetime, timedelta

from app.models import CanvasCourse, CanvasItem, Course
from app.services.practice.scheduling import interval_for
from app.services.study.horizon import HORIZON_SHARE, next_exam


NU = datetime(2026, 9, 22, 12, 0, 0)


def test_without_a_deadline_the_ladder_is_unchanged():
    assert interval_for(1) == timedelta(days=1)
    assert interval_for(5) == timedelta(days=35)


def test_the_interval_never_exceeds_a_fifth_of_the_time_left():
    """Nog 30 dagen: een kaart komt hoogstens na 6 dagen terug, ook boven aan
    de ladder. Zo zie je alles minstens vijf keer terug."""
    assert interval_for(5, horizon_days=30) == timedelta(days=6)
    assert interval_for(3, horizon_days=30) == timedelta(days=6)
    assert interval_for(1, horizon_days=30) == timedelta(days=1)


def test_the_last_days_bring_everything_back(HORIZON=3):
    assert interval_for(5, horizon_days=4) == timedelta(days=1)
    assert interval_for(5, horizon_days=1) == timedelta(days=1)


def test_a_passed_exam_returns_to_the_long_ladder():
    """Het tentamen is geweest; dan is er geen korte horizon meer om op te
    plannen, en telt onthouden op de lange duur weer."""
    assert interval_for(5, horizon_days=0) == timedelta(days=35)
    assert interval_for(5, horizon_days=-3) == timedelta(days=35)


def test_a_wrong_answer_still_comes_back_immediately():
    assert interval_for(0, horizon_days=30) == timedelta(0)


def test_the_share_is_stated_once():
    assert 0.1 <= HORIZON_SHARE <= 0.2


def test_the_exam_from_course_yml_sets_the_horizon(db_session):
    db_session.add(Course(slug="sso", name="SSO", exams=[{"name": "Tentamen", "date": "2026-10-21"}]))
    db_session.commit()

    exam = next_exam(db_session, "sso", now=NU)

    assert exam is not None
    assert exam.name == "Tentamen"
    assert exam.days_left == 29


def test_an_exam_that_has_been_is_not_the_next_one(db_session):
    db_session.add(
        Course(
            slug="sso",
            name="SSO",
            exams=[{"name": "Oud", "date": "2026-06-01"}, {"name": "Tentamen", "date": "2026-10-21"}],
        )
    )
    db_session.commit()

    assert next_exam(db_session, "sso", now=NU).name == "Tentamen"


def test_a_canvas_exam_counts_too_and_the_earliest_wins(db_session):
    """FDS heeft zijn tentamen wél als Canvas-opdracht; SSO niet. Het plan moet
    met allebei overweg."""
    db_session.add(Course(slug="fds", name="FDS", canvas_id=59831, exams=[{"name": "Herkansing", "date": "2026-12-14"}]))
    db_session.add(CanvasCourse(id=59831, name="FDS"))
    db_session.add(
        CanvasItem(
            id="assignment:1",
            canvas_course_id=59831,
            kind="exam",
            title="Final Exam",
            due_at=datetime(2026, 10, 21, 7, 30),
        )
    )
    db_session.commit()

    exam = next_exam(db_session, "fds", now=NU)

    assert exam.name == "Final Exam"
    assert exam.days_left == 29


def test_no_exam_at_all_gives_none(db_session):
    db_session.add(Course(slug="sso", name="SSO", exams=[]))
    db_session.commit()

    assert next_exam(db_session, "sso", now=NU) is None
