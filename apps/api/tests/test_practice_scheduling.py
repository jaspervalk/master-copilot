"""Herhaling wordt afgeleid uit de pogingen, dus deze tests schrijven pogingen
en kijken wat er terugkomt — er is geen planning om apart te controleren."""
from datetime import datetime, timedelta

from app.models import PracticeAttempt, PracticeCard
from app.services.practice.scheduling import (
    INTERVALS_DAYS,
    due_cards,
    due_counts,
    interval_for,
)


NU = datetime(2026, 9, 8, 12, 0, 0)


def _card(db, *, section="Lecture 3", course="sso", created=None, disabled=False):
    card = PracticeCard(
        course_slug=course, document_id="doc", chunk_id="chunk", section_path=section,
        page_start=7, page_end=7, kind="stats", setup="n = 40",
        question=f"Vraag {section} {created}", reference_answer="n / 2",
        created_at=created or (NU - timedelta(days=30)), disabled=disabled,
    )
    db.add(card)
    db.commit()
    return card


def _attempt(db, card, *, correct, when):
    db.add(PracticeAttempt(card_id=card.id, given_answer="20", correct=correct,
                           detail="", created_at=when))
    db.commit()


def test_a_card_you_never_did_is_due(db_session):
    card = _card(db_session)

    klaar = due_cards(db_session, "sso", now=NU)

    assert [item.card.id for item in klaar] == [card.id]
    assert klaar[0].attempts == 0


def test_one_correct_answer_puts_a_card_away_for_a_day(db_session):
    card = _card(db_session)
    _attempt(db_session, card, correct=True, when=NU - timedelta(hours=2))

    assert due_cards(db_session, "sso", now=NU) == []
    morgen = due_cards(db_session, "sso", now=NU + timedelta(days=1))
    assert [item.card.id for item in morgen] == [card.id]
    assert morgen[0].streak == 1


def test_the_interval_grows_with_the_streak(db_session):
    card = _card(db_session)
    for dagen_geleden in (20, 12, 4):
        _attempt(db_session, card, correct=True, when=NU - timedelta(days=dagen_geleden))

    # Drie keer goed: pas over zeven dagen weer, dus vier dagen na de laatste
    # poging staat hij nog niet klaar.
    assert due_cards(db_session, "sso", now=NU) == []
    assert due_cards(db_session, "sso", now=NU + timedelta(days=4)) != []


def test_one_mistake_sends_a_card_back_to_the_start(db_session):
    """Ook al ging het daarvóór tien keer goed."""
    card = _card(db_session)
    for dagen_geleden in range(40, 30, -1):
        _attempt(db_session, card, correct=True, when=NU - timedelta(days=dagen_geleden))
    _attempt(db_session, card, correct=False, when=NU - timedelta(minutes=5))

    klaar = due_cards(db_session, "sso", now=NU)

    assert [item.card.id for item in klaar] == [card.id]
    assert klaar[0].streak == 0


def test_the_interval_stops_growing_at_the_top_of_the_ladder(db_session):
    assert interval_for(len(INTERVALS_DAYS)) == interval_for(len(INTERVALS_DAYS) + 5)
    assert interval_for(0) == timedelta(0)


def test_the_one_waiting_longest_comes_first(db_session):
    oud = _card(db_session, section="Lecture 1", created=NU - timedelta(days=40))
    nieuw = _card(db_session, section="Lecture 2", created=NU - timedelta(days=1))

    klaar = due_cards(db_session, "sso", now=NU)

    assert [item.card.id for item in klaar] == [oud.id, nieuw.id]


def test_what_you_missed_last_time_goes_first(db_session):
    """Anders zakt een kaart die je net miste naar de staart: hij staat immers
    pas net weer klaar."""
    oud = _card(db_session, section="Lecture 1", created=NU - timedelta(days=40))
    gemist = _card(db_session, section="Lecture 2", created=NU - timedelta(days=5))
    _attempt(db_session, gemist, correct=False, when=NU - timedelta(minutes=1))

    klaar = due_cards(db_session, "sso", now=NU)

    assert [item.card.id for item in klaar] == [gemist.id, oud.id]
    assert klaar[0].lapsed and not klaar[1].lapsed


def test_an_exam_question_waits_until_you_have_done_it_once(db_session):
    """Een geïmporteerd proeftentamen gaat over zes weken stof; die hoort niet
    in één klap in je herhaalronde."""
    tentamen = _card(db_session, section="Mock Exam 1 › 5 Ethics")
    tentamen.origin, tentamen.position = "mock-exam-1", 30
    db_session.commit()

    assert due_cards(db_session, "sso", now=NU) == []

    _attempt(db_session, tentamen, correct=False, when=NU - timedelta(minutes=3))

    assert [item.card.id for item in due_cards(db_session, "sso", now=NU)] == [tentamen.id]


def test_a_discarded_card_never_comes_back(db_session):
    _card(db_session, disabled=True)

    assert due_cards(db_session, "sso", now=NU) == []


def test_another_course_stays_out_of_the_round(db_session):
    _card(db_session, course="fundamentals-of-ds")

    assert due_cards(db_session, "sso", now=NU) == []


def test_a_round_can_be_narrowed_to_one_deck(db_session):
    _card(db_session, section="Lecture 1")
    drie = _card(db_session, section="Lecture 3")

    klaar = due_cards(db_session, "sso", now=NU, section_path="Lecture 3")

    assert [item.card.id for item in klaar] == [drie.id]


def test_the_counts_are_per_deck(db_session):
    _card(db_session, section="Lecture 1", created=NU - timedelta(days=3))
    _card(db_session, section="Lecture 1", created=NU - timedelta(days=2))
    net_gedaan = _card(db_session, section="Lecture 3")
    _attempt(db_session, net_gedaan, correct=True, when=NU - timedelta(hours=1))

    assert due_counts(db_session, "sso", now=NU) == {"Lecture 1": 2}
