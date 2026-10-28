"""Wat je nú doet: één ronde, samengesteld uit wat het meest oplevert.

Drie regels, alle drie uit de literatuur en alle drie mechanisch:

* wat je vorige keer fout had gaat voorop (Metcalfe 2017 over leren van fouten);
* herhalen gaat vóór nieuw, maar nieuw wordt nooit helemaal verdrongen — je
  moet ook bijblijven;
* twee kaarten over dezelfde toets staan niet achter elkaar (Rohrer e.a. 2020:
  de winst van interleaving zit in het kiezen van de juiste procedure, en dat
  oefen je niet als ze op een rij staan).
"""
from datetime import datetime, timedelta

from app.models import Course, Document, PracticeAttempt, PracticeCard
from app.services.study.session import MINUTES_PER_KIND, NEW_SHARE, build_session


NU = datetime(2026, 9, 22, 12, 0, 0)


def _course(db, *, exams=None):
    db.add(Course(slug="sso", name="SSO", exams=exams or [], week_plans={}))
    db.commit()


def _document(db, *, week):
    document = Document(
        title=f"Lecture {week}",
        source_path=f"sso/slides/week-{week:02d}/lecture{week}.pdf",
        checksum=f"sha-{week}",
        course_slug="sso",
        doc_kind="slides",
        week=week,
        ingestion_status="indexed",
    )
    db.add(document)
    db.commit()
    return document


def _card(db, document, *, vraag, week=None, procedure=None, kind="stats", made=None):
    spec = {}
    if procedure:
        spec["procedure"] = procedure
    card = PracticeCard(
        course_slug="sso",
        document_id=document.id,
        chunk_id="chunk",
        section_path=f"Lecture {week}",
        page_start=1,
        page_end=1,
        kind=kind,
        setup="n = 40",
        question=vraag,
        reference_answer="n / 2",
        week=week,
        spec=spec,
        created_at=made or (NU - timedelta(days=20)),
    )
    db.add(card)
    db.commit()
    return card


def _attempts(db, card, *, goed, fout_na=False, laatste=None):
    moment = laatste or (NU - timedelta(days=10))
    for _ in range(goed):
        db.add(PracticeAttempt(card_id=card.id, given_answer="20", correct=True, detail="", created_at=moment))
    if fout_na:
        db.add(PracticeAttempt(card_id=card.id, given_answer="0", correct=False, detail="", created_at=moment))
    db.commit()


def test_the_session_fits_in_the_time_you_have(db_session):
    _course(db_session)
    document = _document(db_session, week=3)
    for index in range(20):
        _card(db_session, document, vraag=f"v{index}", week=3)

    sessie = build_session(db_session, "sso", minutes=15, now=NU)

    assert len(sessie.cards) == int(15 / MINUTES_PER_KIND["stats"])
    assert sessie.estimated_minutes <= 15


def test_a_card_you_missed_last_time_comes_first(db_session):
    _course(db_session)
    document = _document(db_session, week=3)
    goed = _card(db_session, document, vraag="goed", week=3)
    _attempts(db_session, goed, goed=1, laatste=NU - timedelta(days=30))
    gemist = _card(db_session, document, vraag="gemist", week=3)
    _attempts(db_session, gemist, goed=1, fout_na=True, laatste=NU - timedelta(days=1))

    sessie = build_session(db_session, "sso", minutes=30, now=NU)

    assert sessie.cards[0].question == "gemist"
    assert sessie.cards[0].reason == "zwak"


def test_repetition_comes_first_but_never_takes_the_whole_round(db_session):
    """Veertig kaarten die aan de beurt zijn mogen niet betekenen dat je de
    nieuwe stof van deze week niet ziet. Andersom net zo."""
    _course(db_session)
    document = _document(db_session, week=3)
    for index in range(40):
        card = _card(db_session, document, vraag=f"oud{index}", week=3)
        _attempts(db_session, card, goed=1, laatste=NU - timedelta(days=30))
    for index in range(40):
        _card(db_session, document, vraag=f"nieuw{index}", week=4)

    sessie = build_session(db_session, "sso", minutes=60, now=NU)

    nieuw = [card for card in sessie.cards if card.reason == "nieuw"]
    herhaald = [card for card in sessie.cards if card.reason == "herhalen"]
    assert len(nieuw) >= 1 and len(herhaald) >= 1
    # Het gereserveerde deel gaat naar nieuw, de rest naar herhalen.
    assert len(herhaald) > len(nieuw)


def test_the_whole_time_is_used_when_there_is_enough_to_do(db_session):
    """Eerder bleef er tijd over doordat het plafond op nieuw bond terwijl er
    niets meer te herhalen viel."""
    _course(db_session)
    document = _document(db_session, week=3)
    oud = _card(db_session, document, vraag="oud", week=3)
    _attempts(db_session, oud, goed=1, laatste=NU - timedelta(days=30))
    for index in range(20):
        _card(db_session, document, vraag=f"nieuw{index}", week=3)

    sessie = build_session(db_session, "sso", minutes=30, now=NU)

    assert sessie.estimated_minutes >= 30 - MINUTES_PER_KIND["stats"]


def test_without_anything_to_repeat_the_session_is_all_new(db_session):
    _course(db_session)
    document = _document(db_session, week=4)
    for index in range(10):
        _card(db_session, document, vraag=f"nieuw{index}", week=4)

    sessie = build_session(db_session, "sso", minutes=30, now=NU)

    assert {card.reason for card in sessie.cards} == {"nieuw"}


def test_two_cards_about_the_same_test_are_not_adjacent(db_session):
    _course(db_session)
    document = _document(db_session, week=3)
    for index in range(4):
        _card(db_session, document, vraag=f"t{index}", week=3, procedure="t-toets")
    for index in range(4):
        _card(db_session, document, vraag=f"chi{index}", week=3, procedure="chi-kwadraat")

    sessie = build_session(db_session, "sso", minutes=60, now=NU)
    procedures = [card.procedure for card in sessie.cards]

    assert len(procedures) == 8
    assert all(links != rechts for links, rechts in zip(procedures, procedures[1:]))


def test_interleaving_falls_back_to_the_week_when_there_is_no_procedure(db_session):
    """Bestaande kaarten dragen geen procedure. Dan is de week het grofste
    onderscheid dat er is, en dat is beter dan niets."""
    _course(db_session)
    for week in (1, 2):
        document = _document(db_session, week=week)
        for index in range(3):
            _card(db_session, document, vraag=f"w{week}-{index}", week=week)

    weken = [card.week for card in build_session(db_session, "sso", minutes=60, now=NU).cards]

    assert all(links != rechts for links, rechts in zip(weken, weken[1:]))


def test_the_exam_date_travels_with_the_session(db_session):
    _course(db_session, exams=[{"name": "Tentamen", "date": "2026-10-21"}])
    document = _document(db_session, week=3)
    _card(db_session, document, vraag="v", week=3)

    sessie = build_session(db_session, "sso", minutes=10, now=NU)

    assert sessie.exam is not None
    assert sessie.exam.days_left == 29


def test_an_empty_course_gives_an_empty_session_with_a_reason(db_session):
    _course(db_session)

    sessie = build_session(db_session, "sso", minutes=30, now=NU)

    assert sessie.cards == []
    assert any("kaart" in note for note in sessie.notes)


def test_a_week_round_stays_inside_that_week(db_session):
    """Vlak na een college wil je de nieuwe stof eerst apart zien; daarna gaat
    hij mee in de gewone ronde, door elkaar met de rest."""
    _course(db_session)
    for week in (2, 3):
        document = _document(db_session, week=week)
        for index in range(3):
            _card(db_session, document, vraag=f"w{week}-{index}", week=week)

    sessie = build_session(db_session, "sso", minutes=60, now=NU, week=3)

    assert {card.week for card in sessie.cards} == {3}


def test_an_empty_week_says_which_week(db_session):
    _course(db_session)
    _card(db_session, _document(db_session, week=2), vraag="v", week=2)

    sessie = build_session(db_session, "sso", minutes=60, now=NU, week=5)

    assert sessie.cards == []
    assert "week 5" in sessie.notes[0]


def test_the_round_draws_from_every_corner_not_just_the_oldest_pile(db_session):
    """Op echte data ging dit mis: dertig kaarten uit week 1 waren het oudst,
    dus een ronde van 45 minuten bestond uit vijftien kaarten over hetzelfde
    onderwerp — en dan valt er niets af te wisselen. De keuze zelf moet
    spreiden, niet pas de volgorde achteraf."""
    _course(db_session)
    for week, procedure in ((1, "t-toets"), (2, "tekentoets"), (3, "regressie"), (4, "logistische regressie")):
        document = _document(db_session, week=week)
        for index in range(15):
            _card(db_session, document, vraag=f"w{week}-{index}", week=week, procedure=procedure)
    # De kaarten van week 1 zijn het oudst.
    for card in db_session.query(PracticeCard).filter(PracticeCard.week == 1):
        card.created_at = NU - timedelta(days=60)
    db_session.commit()

    sessie = build_session(db_session, "sso", minutes=45, now=NU)
    procedures = [card.procedure for card in sessie.cards]

    assert len(set(procedures)) >= 3
    assert all(links != rechts for links, rechts in zip(procedures, procedures[1:]))


def test_new_material_comes_from_every_week_newest_first(db_session):
    """Dertig oude kaarten uit week 1 en drie verse uit week 5: een korte ronde
    moet het college van deze week bevatten. Op volgorde van aanmaken kwam je
    pas bij week 5 als alles van week 1 tot en met 4 op was — en dan loop je
    achter op precies de stof die je nu wilt bijhouden."""
    _course(db_session)
    oud = _document(db_session, week=1)
    for index in range(30):
        _card(db_session, oud, vraag=f"oud{index}", week=1, procedure=f"p{index % 5}", made=NU - timedelta(days=20))
    vers = _document(db_session, week=5)
    for index in range(3):
        _card(db_session, vers, vraag=f"vers{index}", week=5, procedure=f"q{index}", made=NU - timedelta(hours=2))

    sessie = build_session(db_session, "sso", minutes=15, now=NU)

    assert any(card.week == 5 for card in sessie.cards)
    assert sessie.cards[0].week == 5 or sessie.cards[1].week == 5


def test_every_week_gets_a_turn_in_a_long_round(db_session):
    _course(db_session)
    for week in (1, 2, 3, 4, 5):
        document = _document(db_session, week=week)
        for index in range(6):
            _card(db_session, document, vraag=f"w{week}-{index}", week=week, procedure=f"w{week}p{index % 3}")

    weken = {card.week for card in build_session(db_session, "sso", minutes=45, now=NU).cards}

    assert weken == {1, 2, 3, 4, 5}
