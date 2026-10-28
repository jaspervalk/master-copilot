"""Wat weet je al, en wat nog niet.

Net als de herhaling wordt beheersing afgeleid uit `practice_attempts`; er is
geen tweede administratie. Deze tests schrijven dus pogingen en kijken welke
staat eruit komt.
"""
from datetime import datetime, timedelta

from app.models import Document, PracticeAttempt, PracticeCard
from app.services.study.mastery import (
    BEHEERST,
    LEREND,
    MASTERY_STREAK,
    NIEUW,
    ZWAK,
    card_states,
)


NU = datetime(2026, 9, 22, 12, 0, 0)


def _document(db, *, week=None, slug="sso", doc_id=None):
    document = Document(
        id=doc_id,
        title=f"Lecture {week}",
        source_path=f"{slug}/slides/week-{week or 0:02d}/lecture{week or 0}.pdf",
        checksum=f"sha-{week}-{doc_id}",
        course_slug=slug,
        doc_kind="slides",
        week=week,
        ingestion_status="indexed",
    )
    db.add(document)
    db.commit()
    return document


def _card(db, *, document, week=None, topic=None, course="sso", vraag="Toets de kans"):
    card = PracticeCard(
        course_slug=course,
        document_id=document.id,
        chunk_id="chunk",
        section_path="Lecture 5",
        page_start=1,
        page_end=1,
        kind="stats",
        setup="n = 40",
        question=vraag,
        reference_answer="n / 2",
        week=week,
        spec={"topic": topic} if topic else {},
        created_at=NU - timedelta(days=30),
    )
    db.add(card)
    db.commit()
    return card


def _attempt(db, card, *, correct, when):
    db.add(
        PracticeAttempt(card_id=card.id, given_answer="20", correct=correct, detail="", created_at=when)
    )
    db.commit()


def test_a_card_you_never_did_is_new(db_session):
    card = _card(db_session, document=_document(db_session, week=3))

    states = card_states(db_session, "sso", now=NU)

    assert [state.card_id for state in states] == [card.id]
    assert states[0].state == NIEUW
    assert states[0].attempts == 0


def test_one_good_answer_is_not_yet_mastery(db_session):
    card = _card(db_session, document=_document(db_session, week=3))
    _attempt(db_session, card, correct=True, when=NU - timedelta(days=1))

    assert card_states(db_session, "sso", now=NU)[0].state == LEREND


def test_a_streak_of_three_counts_as_mastered(db_session):
    card = _card(db_session, document=_document(db_session, week=3))
    for day in range(MASTERY_STREAK):
        _attempt(db_session, card, correct=True, when=NU - timedelta(days=10 - day))

    state = card_states(db_session, "sso", now=NU)[0]

    assert state.state == BEHEERST
    assert state.streak == MASTERY_STREAK


def test_one_mistake_makes_a_card_weak_again(db_session):
    """Een fout zet de reeks op nul, en dan is 'beheerst' niet meer waar — ook
    niet als het er daarvóór tien keer goed ging."""
    card = _card(db_session, document=_document(db_session, week=3))
    for day in range(4):
        _attempt(db_session, card, correct=True, when=NU - timedelta(days=20 - day))
    _attempt(db_session, card, correct=False, when=NU - timedelta(days=1))

    state = card_states(db_session, "sso", now=NU)[0]

    assert state.state == ZWAK
    assert state.streak == 0


def test_a_card_without_a_week_takes_the_week_of_its_document(db_session):
    """Kaarten uit de eerste ronde dragen geen week; hun document wel. Zonder
    deze afleiding valt alles wat er al staat buiten het weekoverzicht."""
    card = _card(db_session, document=_document(db_session, week=2), week=None)

    assert card_states(db_session, "sso", now=NU)[0].week == 2


def test_the_week_on_the_card_wins_from_the_document(db_session):
    """Een kaart uit een boek is gemaakt vóór een week; het boek zelf heeft er
    geen. Wat bij het maken is vastgelegd, is de waarheid."""
    card = _card(db_session, document=_document(db_session, week=None), week=4)

    assert card_states(db_session, "sso", now=NU)[0].week == 4


def test_the_topic_comes_from_the_card_and_is_optional(db_session):
    document = _document(db_session, week=3)
    _card(db_session, document=document, topic="logistische regressie", vraag="a")
    _card(db_session, document=document, topic=None, vraag="b")

    topics = sorted((state.topic or "") for state in card_states(db_session, "sso", now=NU))

    assert topics == ["", "logistische regressie"]


def test_a_discarded_card_does_not_count(db_session):
    card = _card(db_session, document=_document(db_session, week=3))
    card.disabled = True
    db_session.commit()

    assert card_states(db_session, "sso", now=NU) == []


def test_another_course_stays_out(db_session):
    _card(db_session, document=_document(db_session, week=3, slug="fundamentals-of-ds"), course="fundamentals-of-ds")

    assert card_states(db_session, "sso", now=NU) == []
