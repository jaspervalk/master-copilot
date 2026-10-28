"""Per week: hoeveel stof er is, hoeveel kaarten, en hoeveel je ervan kent.

Dit is het overzicht waarop de oefenpagina en het plan draaien. Het mag niets
raden: een week zonder kaarten heet een week zonder kaarten, en een onderwerp
uit course.yml waar geen kaart bij hoort wordt met naam genoemd.
"""
from datetime import datetime, timedelta

from app.models import Chunk, Course, Document, PracticeAttempt, PracticeCard, WeekSummary
from app.services.study.coverage import week_coverage


NU = datetime(2026, 9, 22, 12, 0, 0)


def _course(db, *, slug="sso", week_plans=None):
    course = Course(slug=slug, name="SSO", week_plans=week_plans or {})
    db.add(course)
    db.commit()
    return course


def _document(db, *, week, slug="sso", chunks=0, kind="slides"):
    document = Document(
        title=f"Lecture {week}",
        source_path=f"{slug}/{kind}/week-{week:02d}/lecture{week}.pdf",
        checksum=f"sha-{slug}-{kind}-{week}",
        course_slug=slug,
        doc_kind=kind,
        week=week,
        ingestion_status="indexed",
    )
    db.add(document)
    db.flush()
    for index in range(chunks):
        db.add(
            Chunk(
                document_id=document.id,
                chunk_index=index,
                section_path=f"Lecture {week} › slide {index}",
                page_start=index + 1,
                page_end=index + 1,
                token_count=10,
                text="tekst",
                normalized_text="tekst",
            )
        )
    db.commit()
    return document


def _card(db, *, document, week, topic=None, vraag="v", course="sso"):
    card = PracticeCard(
        course_slug=course,
        document_id=document.id,
        chunk_id="chunk",
        section_path=f"Lecture {week}",
        page_start=1,
        page_end=1,
        kind="stats",
        setup="n = 40",
        question=vraag,
        reference_answer="n / 2",
        week=week,
        spec={"topic": topic} if topic else {},
        created_at=NU - timedelta(days=20),
    )
    db.add(card)
    db.commit()
    return card


def _attempts(db, card, *, goed: int, fout_na=False):
    moment = NU - timedelta(days=15)
    for _ in range(goed):
        db.add(PracticeAttempt(card_id=card.id, given_answer="20", correct=True, detail="", created_at=moment))
        moment += timedelta(days=1)
    if fout_na:
        db.add(PracticeAttempt(card_id=card.id, given_answer="0", correct=False, detail="", created_at=moment))
    db.commit()


def test_a_week_from_course_yml_shows_up_even_without_cards(db_session):
    """Week 4 bestaat in de studiewijzer; dat hij leeg is, is juist het bericht."""
    _course(db_session, week_plans={"4": {"lectures": [7], "topics": ["logistische regressie"], "reading": []}})
    _document(db_session, week=4, chunks=3)

    weken = week_coverage(db_session, "sso", now=NU)

    assert [week.week for week in weken] == [4]
    assert weken[0].lectures == [7]
    assert weken[0].topics == ["logistische regressie"]
    assert weken[0].cards == 0
    assert weken[0].material_chunks == 3


def test_cards_are_counted_per_state(db_session):
    _course(db_session, week_plans={"3": {"lectures": [5, 6], "topics": [], "reading": []}})
    document = _document(db_session, week=3, chunks=1)
    beheerst = _card(db_session, document=document, week=3, vraag="a")
    _attempts(db_session, beheerst, goed=3)
    zwak = _card(db_session, document=document, week=3, vraag="b")
    _attempts(db_session, zwak, goed=2, fout_na=True)
    _card(db_session, document=document, week=3, vraag="c")

    week = week_coverage(db_session, "sso", now=NU)[0]

    assert (week.cards, week.mastered, week.weak, week.new) == (3, 1, 1, 1)


def test_a_topic_without_a_card_is_named(db_session):
    """Zo weet je waar nog geen oefening voor bestaat, zonder te gokken of de
    kaarten die er zijn dat onderwerp toevallig ook raken."""
    _course(
        db_session,
        week_plans={"4": {"lectures": [7], "topics": ["logistische regressie", "GAM"], "reading": []}},
    )
    document = _document(db_session, week=4, chunks=1)
    _card(db_session, document=document, week=4, topic="logistische regressie")

    week = week_coverage(db_session, "sso", now=NU)[0]

    assert week.topics_without_cards == ["GAM"]


def test_a_week_that_only_has_material_is_shown_too(db_session):
    """Slides van college 7 kunnen er staan voordat week 4 in course.yml komt."""
    _course(db_session, week_plans={})
    _document(db_session, week=4, chunks=2)

    weken = week_coverage(db_session, "sso", now=NU)

    assert [week.week for week in weken] == [4]
    assert weken[0].topics == []


def test_the_summary_state_travels_with_the_week(db_session):
    _course(db_session, week_plans={"1": {"lectures": [1], "topics": [], "reading": []}})
    _document(db_session, week=1, chunks=1)
    db_session.add(
        WeekSummary(
            course_slug="sso",
            week=1,
            content={"thread": "x", "topics": [], "concepts": [], "skills": []},
            source_fingerprint="oud",
            chunks_used=1,
            chunks_total=1,
        )
    )
    db_session.commit()

    week = week_coverage(db_session, "sso", now=NU)[0]

    assert week.has_summary is True
    assert week.summary_stale is True  # de vingerafdruk klopt niet meer


def test_weeks_come_out_in_order(db_session):
    _course(db_session, week_plans={"2": {"lectures": [], "topics": [], "reading": []}})
    _document(db_session, week=4, chunks=1)
    _document(db_session, week=1, chunks=1)

    assert [week.week for week in week_coverage(db_session, "sso", now=NU)] == [1, 2, 4]


def test_a_topic_counts_as_covered_when_the_words_really_line_up(db_session):
    """Tentamenkaarten dragen het onderwerp van de transcriptie, niet dat van
    course.yml: "numpy broadcasting" tegenover "numpy". Woordelijk vergelijken
    meldde dan dat er geen kaarten waren terwijl er honderd stonden."""
    _course(db_session, week_plans={"1": {"lectures": [1], "topics": ["numpy", "pandas"], "reading": []}})
    document = _document(db_session, week=1, chunks=1)
    _card(db_session, document=document, week=1, topic="numpy broadcasting", vraag="a")

    week = week_coverage(db_session, "sso", now=NU)[0]

    assert week.topics_without_cards == ["pandas"]


def test_a_topic_that_only_shares_a_container_word_is_not_covered(db_session):
    """"Statistical Learning — Supervised Learning" zegt niets over "naive
    bayes"; daar hoort wél een melding te komen."""
    _course(
        db_session,
        week_plans={"3": {"lectures": [5], "topics": ["naive bayes", "k-NN"], "reading": []}},
    )
    document = _document(db_session, week=3, chunks=1)
    _card(db_session, document=document, week=3, topic="Statistical Learning — Supervised Learning", vraag="a")

    week = week_coverage(db_session, "sso", now=NU)[0]

    assert week.topics_without_cards == ["naive bayes", "k-NN"]
