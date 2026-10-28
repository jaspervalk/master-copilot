"""De studeerpagina haalt alles in één keer op, zoals de agenda dat doet."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import Chunk, Course, Document, PracticeAttempt, PracticeCard


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _material(db, *, week=3, cards=6, attempts=False):
    db.add(
        Course(
            slug="sso",
            name="SSO",
            exams=[{"name": "Tentamen", "date": "2099-10-21"}],
            week_plans={str(week): {"lectures": [5], "topics": ["lineaire regressie", "GAM"], "reading": []}},
        )
    )
    document = Document(
        title="Lecture 5",
        source_path="sso/slides/week-03/lecture5.pdf",
        checksum="a" * 64,
        course_slug="sso",
        doc_kind="slides",
        week=week,
        ingestion_status="indexed",
    )
    document.chunks.append(
        Chunk(
            chunk_index=0, section_path="Lecture 5 › slide 1", page_start=1, page_end=1,
            token_count=10, text="regressie", normalized_text="regressie", chunk_metadata={},
        )
    )
    db.add(document)
    db.flush()
    for index in range(cards):
        card = PracticeCard(
            course_slug="sso", document_id=document.id, chunk_id="c", section_path="Lecture 5",
            page_start=1, page_end=1, kind="stats", setup="n = 4", question=f"vraag {index}",
            reference_answer="n", week=week, spec={"topic": "lineaire regressie"},
            created_at=datetime.utcnow() - timedelta(days=5),
        )
        db.add(card)
        db.flush()
        if attempts and index == 0:
            db.add(
                PracticeAttempt(
                    card_id=card.id, given_answer="4", correct=False, detail="",
                    created_at=datetime.utcnow() - timedelta(days=1),
                )
            )
    db.commit()
    return document


def test_the_page_gets_session_weeks_and_exam_in_one_call(client, db_session):
    _material(db_session, attempts=True)

    body = client.get("/api/study", params={"course_slug": "sso", "minutes": 15}).json()

    assert body["exam"]["name"] == "Tentamen"
    assert body["exam"]["days_left"] > 0
    assert body["session"]["minutes"] == 15
    assert body["session"]["estimated_minutes"] <= 15
    # De gemiste kaart staat vooraan, met de reden erbij.
    assert body["session"]["cards"][0]["reason"] == "zwak"
    assert body["session"]["cards"][0]["card"]["question"] == "vraag 0"
    assert body["weeks"][0]["week"] == 3
    assert body["weeks"][0]["topics_without_cards"] == ["GAM"]
    assert body["totals"]["cards"] == 6


def test_a_course_without_cards_says_what_to_do(client, db_session):
    db_session.add(Course(slug="sso", name="SSO", week_plans={}))
    db_session.commit()

    body = client.get("/api/study", params={"course_slug": "sso"}).json()

    assert body["session"]["cards"] == []
    assert body["session"]["notes"]
    assert body["weeks"] == []


def test_the_session_never_exceeds_the_time_asked_for(client, db_session):
    _material(db_session, cards=40)

    body = client.get("/api/study", params={"course_slug": "sso", "minutes": 10}).json()

    assert body["session"]["estimated_minutes"] <= 10


def test_an_impossible_time_is_refused(client, db_session):
    assert client.get("/api/study", params={"course_slug": "sso", "minutes": 0}).status_code == 422


def test_filling_a_week_without_a_model_is_a_clear_error(client, db_session):
    """Zonder OpenAI-sleutel kan er niets gemaakt worden; dat hoort een nette
    400 te zijn, geen stacktrace."""
    _material(db_session)

    response = client.post(
        "/api/study/weeks/3/cards", json={"course_slug": "sso", "kind": "keuze", "count": 2}
    )

    assert response.status_code == 400
    assert "model" in response.json()["detail"]


def test_the_page_says_whether_the_pace_is_enough(client, db_session):
    """De som staat in het antwoord, niet alleen de kaarten: zonder tempo weet
    je niet of al dat oefenen op tijd rond komt."""
    _material(db_session, cards=40)

    body = client.get("/api/study", params={"course_slug": "sso", "minutes": 15}).json()

    assert body["pace"]["cards"] == 40
    assert body["pace"]["reviews_needed"] == 80
    assert body["pace"]["days_left"] > 0
    assert isinstance(body["pace"]["feasible"], bool)


def test_a_course_without_an_exam_has_no_pace(client, db_session):
    db_session.add(Course(slug="dl", name="Deep Learning", week_plans={}, exams=[]))
    db_session.commit()

    assert client.get("/api/study", params={"course_slug": "dl"}).json()["pace"] is None
