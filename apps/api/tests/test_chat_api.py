import pytest
from fastapi.testclient import TestClient

from app.api.routes import chat as chat_route
from app.db import get_db
from app.main import app
from app.models import Conversation, Message, QueryLog
from app.schemas import AnswerResponse, QueryChunkResult


def _chunk() -> QueryChunkResult:
    return QueryChunkResult(
        chunk_id="chunk-1",
        document_id="doc-1",
        document_title="Bishop PRML",
        source_path="dl/books/bishop.pdf",
        course_slug="dl",
        doc_kind="book",
        week=None,
        assignment_status=None,
        section_path="5 Neural Networks",
        page_start=241,
        page_end=242,
        score=0.8,
        text="Backpropagation past de kettingregel toe.",
        chunk_metadata={},
    )


class _FakeAnswering:
    def __init__(self) -> None:
        self.calls = []
        self.client = None

    def compose(self, *, question, retrieval_query, top_k, filters, mode, style, coach=None, language="auto"):
        self.calls.append(
            {"question": question, "retrieval_query": retrieval_query, "style": style, "coach": coach, "language": language}
        )
        return AnswerResponse(
            coach=coach.echo if coach else None,
            question=question,
            rewritten_query=retrieval_query,
            answer="Uitleg [1]",
            abstained=False,
            confidence="high",
            confidence_reasons=["3 fragmenten opgehaald."],
            citations=[],
            retrieved_chunks=[_chunk()],
            embedding_provider="local-hash",
            answer_model="local-extractive",
            answer_style=style,
            latency_ms=42,
        )


@pytest.fixture()
def client(db_session, monkeypatch):
    fake = _FakeAnswering()
    monkeypatch.setattr(chat_route, "AnsweringService", lambda: fake)
    monkeypatch.setattr(chat_route.query_logs, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        test_client.fake_answering = fake
        yield test_client
    app.dependency_overrides.clear()


def test_chat_creates_a_conversation_and_two_messages(client, db_session):
    response = client.post("/api/chat", json={"question": "Wat is backprop?", "filters": {"course_slug": "dl"}})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conversation_id"]
    assert body["answer"] == "Uitleg [1]"
    assert db_session.query(Conversation).count() == 1
    assert db_session.query(Message).count() == 2


def test_second_turn_reuses_the_conversation(client, db_session):
    first = client.post("/api/chat", json={"question": "Wat is backprop?"}).json()

    client.post(
        "/api/chat",
        json={"question": "En waarom werkt dat?", "conversation_id": first["conversation_id"]},
    )

    assert db_session.query(Conversation).count() == 1
    assert db_session.query(Message).count() == 4


def test_answer_style_is_passed_through(client):
    client.post("/api/chat", json={"question": "Wat is backprop?", "answer_style": "short"})

    assert client.fake_answering.calls[-1]["style"] == "short"


def test_every_chat_call_is_logged(client, db_session):
    client.post("/api/chat", json={"question": "Wat is backprop?"})

    row = db_session.query(QueryLog).one()
    assert row.endpoint == "chat"
    assert row.status == "ok"


def test_conversation_detail_returns_the_turns(client):
    conversation_id = client.post("/api/chat", json={"question": "Wat is backprop?"}).json()["conversation_id"]

    response = client.get(f"/api/conversations/{conversation_id}")

    assert response.status_code == 200
    roles = [message["role"] for message in response.json()["messages"]]
    assert roles == ["user", "assistant"]


def test_unknown_conversation_returns_404(client):
    assert client.get("/api/conversations/bestaat-niet").status_code == 404


def _open_assignment(db_session, *, status="open"):
    from app.models import Chunk, Document

    document = Document(
        title="Assignment I", source_path="sso/assignments/week-04/a1.pdf", checksum="0" * 64,
        course_slug="sso", doc_kind="assignment", week=4, assignment_status=status, ingestion_status="indexed",
    )
    document.chunks.append(Chunk(
        chunk_index=0, section_path="Opgave 1", page_start=1, page_end=1,
        token_count=2, text="Opgave 1", normalized_text="opgave 1", chunk_metadata={},
    ))
    db_session.add(document)
    db_session.commit()
    return document


def test_chat_with_coach_pins_the_assignment_and_echoes_it(client, db_session):
    document = _open_assignment(db_session)

    response = client.post("/api/chat", json={
        "question": "hoe begin ik?", "filters": {"course_slug": "sso"},
        "coach": {"document_id": document.id},
    })

    assert response.status_code == 200, response.text
    coach = client.fake_answering.calls[-1]["coach"]
    assert coach.policy == "hints"
    assert [c.section_path for c in coach.pinned] == ["Opgave 1"]
    assert response.json()["coach"]["document_title"] == "Assignment I"


def test_chat_with_coach_on_a_closed_assignment_is_400(client, db_session):
    document = _open_assignment(db_session, status="closed")

    response = client.post("/api/chat", json={
        "question": "hoe begin ik?", "filters": {"course_slug": "sso"},
        "coach": {"document_id": document.id},
    })

    assert response.status_code == 400
    assert "closed" in response.json()["detail"]
