"""Wat er nu aandacht vraagt, in drie getallen voor de navigatiebalk.

Bewust klein: dit draait bij elke paginawissel, dus er mag geen Canvas aan te
pas komen en er wordt niets herrekend wat de agenda al kan. De status en de
bucket komen uit dezelfde functies als de agenda zelf — anders zou de balk iets
anders kunnen zeggen dan de pagina waar hij naartoe wijst.
"""
from datetime import date, datetime, timedelta

from app.models import CanvasCourse, CanvasItem, Course, Document, PracticeCard, Task
from app.services.attention import attention


NU = datetime(2026, 9, 22, 12, 0, 0)  # dinsdag 22 september, 14:00 in Amsterdam


def _vak(db, *, slug="sso", canvas_id=59863, hidden=False):
    db.add(Course(slug=slug, name=slug.upper(), canvas_id=canvas_id, exams=[]))
    db.add(CanvasCourse(id=canvas_id, name=slug.upper(), hidden=hidden))
    db.commit()


def _item(db, *, id="assignment:1", canvas_course_id=59863, due, kind="assignment", submission=None, done=False):
    db.add(
        CanvasItem(
            id=id,
            canvas_course_id=canvas_course_id,
            kind=kind,
            title="Assignment 1",
            due_at=due,
            submission=submission or {},
            done_at=NU if done else None,
        )
    )
    db.commit()


def _kaart(db, *, slug="sso", vraag="v", gemaakt=None):
    document = Document(
        title="Lecture 1", source_path=f"{slug}/slides/week-01/{vraag}.pdf", checksum=f"sha-{vraag}",
        course_slug=slug, doc_kind="slides", week=1, ingestion_status="indexed",
    )
    db.add(document)
    db.flush()
    db.add(
        PracticeCard(
            course_slug=slug, document_id=document.id, chunk_id="c", section_path="Lecture 1",
            page_start=1, page_end=1, kind="stats", setup="n = 4", question=vraag,
            reference_answer="n", created_at=gemaakt or (NU - timedelta(days=3)),
        )
    )
    db.commit()


def test_an_empty_installation_is_all_zeroes(db_session):
    telling = attention(db_session, now=NU)

    assert (telling.today, telling.overdue, telling.due_cards) == (0, 0, 0)


def test_a_deadline_today_counts_as_today(db_session):
    _vak(db_session)
    _item(db_session, due=datetime(2026, 9, 22, 21, 59))

    assert attention(db_session, now=NU).today == 1


def test_a_deadline_that_passed_counts_as_overdue_not_today(db_session):
    _vak(db_session)
    _item(db_session, due=datetime(2026, 9, 22, 6, 0))

    telling = attention(db_session, now=NU)

    assert (telling.today, telling.overdue) == (0, 1)


def test_something_you_handed_in_or_ticked_off_does_not_count(db_session):
    _vak(db_session)
    _item(db_session, id="assignment:1", due=datetime(2026, 9, 22, 21, 59), submission={"submitted_at": "2026-09-20T10:00:00Z"})
    _item(db_session, id="assignment:2", due=datetime(2026, 9, 22, 21, 59), done=True)

    telling = attention(db_session, now=NU)

    assert (telling.today, telling.overdue) == (0, 0)


def test_a_hidden_course_stays_out(db_session):
    """Een oud vak dat in Canvas nog 'actief' heet, heb je hier weggezet."""
    _vak(db_session, slug="oud", canvas_id=6056, hidden=True)
    _item(db_session, canvas_course_id=6056, due=datetime(2026, 9, 22, 21, 59))

    assert attention(db_session, now=NU).today == 0


def test_tasks_of_a_hidden_course_stay_out(db_session):
    _vak(db_session, slug="oud", canvas_id=6056, hidden=True)
    db_session.add(Task(title="Oefententamen oud vak", due_on=date(2026, 9, 18), course_slug="oud"))
    db_session.commit()

    assert attention(db_session, now=NU).overdue == 0


def test_your_own_tasks_count_too(db_session):
    db_session.add(Task(title="Samenvatting maken", due_on=date(2026, 9, 22)))
    db_session.add(Task(title="Was ik vergeten", due_on=date(2026, 9, 18)))
    db_session.add(Task(title="Al gedaan", due_on=date(2026, 9, 22), done_at=NU))
    db_session.commit()

    telling = attention(db_session, now=NU)

    assert (telling.today, telling.overdue) == (1, 1)


def test_a_deleted_task_does_not_count(db_session):
    db_session.add(Task(title="Weg", due_on=date(2026, 9, 22), deleted_at=NU))
    db_session.commit()

    assert attention(db_session, now=NU).today == 0


def test_cards_that_are_due_are_counted_over_all_courses(db_session):
    _vak(db_session)
    _vak(db_session, slug="fds", canvas_id=59831)
    _kaart(db_session, slug="sso", vraag="a")
    _kaart(db_session, slug="fds", vraag="b")
    # Een kaart die pas morgen klaarstaat telt niet.
    _kaart(db_session, slug="sso", vraag="c", gemaakt=NU + timedelta(days=1))

    assert attention(db_session, now=NU).due_cards == 2


def test_cards_of_a_hidden_course_are_not_waiting_for_you(db_session):
    """Een verborgen vak doe je niet meer: zijn kaarten staan niet 'klaar'."""
    _vak(db_session)
    _vak(db_session, slug="fds", canvas_id=59831, hidden=True)
    _kaart(db_session, slug="sso", vraag="a")
    _kaart(db_session, slug="fds", vraag="b")

    assert attention(db_session, now=NU).due_cards == 1
