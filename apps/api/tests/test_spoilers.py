from app.models import Document
from app.services.spoilers import is_hidden, open_assignment_weeks


def _doc(db, *, course, kind, week, status=None):
    db.add(Document(
        title=f"{kind}-{week}", source_path=f"{course}/{kind}s/week-{week:02d}/{kind}.pdf",
        checksum=f"{week:064d}", course_slug=course, doc_kind=kind, week=week,
        assignment_status=status, ingestion_status="indexed",
    ))
    db.commit()


def test_only_open_graded_assignments_hide_their_week(db_session):
    _doc(db_session, course="sso", kind="assignment", week=4, status="open")
    _doc(db_session, course="sso", kind="assignment", week=2, status="closed")
    _doc(db_session, course="sso", kind="assignment", week=3, status="submitted")
    _doc(db_session, course="fds", kind="assignment", week=4, status="open")

    assert open_assignment_weeks(db_session) == {"sso": {4}, "fds": {4}}


def test_exercises_never_hide_anything(db_session):
    _doc(db_session, course="sso", kind="exercise", week=2)

    assert open_assignment_weeks(db_session) == {}


def test_is_hidden_only_for_solutions_and_submissions_in_open_weeks():
    hidden = {"sso": {4}}

    assert is_hidden("sso", "solution", 4, hidden)
    assert is_hidden("sso", "submission", 4, hidden)
    assert not is_hidden("sso", "solution", 2, hidden)
    assert not is_hidden("sso", "book", None, hidden)
    assert not is_hidden("fds", "solution", 4, hidden)
    assert not is_hidden("sso", "solution", 4, None)
