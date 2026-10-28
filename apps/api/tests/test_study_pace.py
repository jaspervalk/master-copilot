"""Haal je het? Kaarten, dagen en minuten tegen elkaar afgezet.

De literatuur is hier ongewoon eenduidig: wat over vier weken telt is niet een
slimmer algoritme maar of élke kaart vóór het tentamen minstens twee keer op
afstand goed is gegaan. Dat is te rekenen, dus dat hoort de pagina te zeggen in
plaats van het aan je gevoel over te laten.

De rekensom is met opzet optimistisch — hij gaat ervan uit dat je alles goed
hebt — en dat staat er ook bij. Een fout kost een extra beurt.
"""
from datetime import datetime, timedelta

from app.models import Course, Document, PracticeAttempt, PracticeCard
from app.services.study.pace import TARGET_SUCCESSES, pace


NU = datetime(2026, 9, 22, 12, 0, 0)


def _course(db, *, exams=None):
    db.add(Course(slug="sso", name="SSO", exams=exams or [{"name": "Tentamen", "date": "2026-10-21"}]))
    db.commit()


def _document(db):
    document = Document(
        title="Lecture 1", source_path="sso/slides/week-01/lecture1.pdf", checksum="a" * 64,
        course_slug="sso", doc_kind="slides", week=1, ingestion_status="indexed",
    )
    db.add(document)
    db.commit()
    return document


def _cards(db, document, *, aantal, kind="stats", goed=0):
    for index in range(aantal):
        card = PracticeCard(
            course_slug="sso", document_id=document.id, chunk_id="c", section_path="Lecture 1",
            page_start=1, page_end=1, kind=kind, setup="n = 4", question=f"v{index}-{kind}-{goed}",
            reference_answer="n", week=1, created_at=NU - timedelta(days=5),
        )
        db.add(card)
        db.flush()
        for keer in range(goed):
            db.add(
                PracticeAttempt(
                    card_id=card.id, given_answer="2", correct=True, detail="",
                    created_at=NU - timedelta(days=4 - keer),
                )
            )
    db.commit()


def test_without_an_exam_there_is_nothing_to_pace(db_session):
    db_session.add(Course(slug="sso", name="SSO", exams=[]))
    db_session.commit()
    _cards(db_session, _document(db_session), aantal=10)

    assert pace(db_session, "sso", minutes=25, now=NU) is None


def test_every_card_needs_two_successes_before_the_exam(db_session):
    _course(db_session)
    _cards(db_session, _document(db_session), aantal=10)

    tempo = pace(db_session, "sso", minutes=25, now=NU)

    assert tempo.cards == 10
    assert tempo.reviews_needed == 10 * TARGET_SUCCESSES


def test_what_you_already_know_does_not_count_again(db_session):
    """Een kaart die je twee keer goed had, hoeft niet nog twee keer."""
    _course(db_session)
    document = _document(db_session)
    _cards(db_session, document, aantal=4, goed=0)
    _cards(db_session, document, aantal=6, goed=TARGET_SUCCESSES)

    tempo = pace(db_session, "sso", minutes=25, now=NU)

    assert tempo.reviews_needed == 4 * TARGET_SUCCESSES


def test_a_comfortable_pace_says_so(db_session):
    _course(db_session)
    _cards(db_session, _document(db_session), aantal=5)

    tempo = pace(db_session, "sso", minutes=45, now=NU)

    assert tempo.feasible is True
    assert tempo.minutes_per_day_needed <= 45


def test_too_much_work_for_the_time_left_says_how_much_is_needed(db_session):
    _course(db_session)
    _cards(db_session, _document(db_session), aantal=400)

    tempo = pace(db_session, "sso", minutes=15, now=NU)

    assert tempo.feasible is False
    assert tempo.minutes_per_day_needed > 15
    # 800 beurten van drie minuten over 29 dagen is ruim tachtig minuten per dag.
    assert 60 < tempo.minutes_per_day_needed < 120


def test_the_day_of_the_exam_no_longer_counts_as_a_study_day(db_session):
    _course(db_session, exams=[{"name": "Tentamen", "date": "2026-09-23"}])
    _cards(db_session, _document(db_session), aantal=10)

    tempo = pace(db_session, "sso", minutes=25, now=NU)

    assert tempo.days_left == 1
    assert tempo.feasible is False


def test_an_exam_today_does_not_divide_by_zero(db_session):
    _course(db_session, exams=[{"name": "Tentamen", "date": "2026-09-22"}])
    _cards(db_session, _document(db_session), aantal=10)

    tempo = pace(db_session, "sso", minutes=25, now=NU)

    assert tempo.days_left == 0
    assert tempo.feasible is False
    assert tempo.minutes_per_day_needed >= 0


def test_nothing_left_to_do_is_feasible(db_session):
    _course(db_session)
    _cards(db_session, _document(db_session), aantal=5, goed=TARGET_SUCCESSES)

    tempo = pace(db_session, "sso", minutes=15, now=NU)

    assert tempo.reviews_needed == 0
    assert tempo.feasible is True
