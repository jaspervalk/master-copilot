from app.models import QueryLog
from app.schemas import AnswerResponse, QueryFilters
from app.services import query_logs


def _answer() -> AnswerResponse:
    return AnswerResponse(
        question="Wat is de ELBO?",
        rewritten_query="uitleg evidence lower bound",
        answer="Uitleg [1]",
        abstained=False,
        confidence="medium",
        confidence_reasons=["2 fragmenten opgehaald."],
        citations=[],
        retrieved_chunks=[],
        embedding_provider="local-hash",
        answer_model="local-extractive",
        answer_style="explain",
    )


def test_answer_is_logged_with_the_rewritten_query(db_session, monkeypatch):
    monkeypatch.setattr(query_logs, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    query_logs.log_answer(
        endpoint="chat",
        question="En waarom werkt dat?",
        response=_answer(),
        filters=QueryFilters(course_slug="dl", week=3),
        top_k=8,
        mode="hybrid",
        conversation_id="conv-1",
        latency_ms=120,
    )

    row = db_session.query(QueryLog).one()
    assert row.rewritten_query == "uitleg evidence lower bound"
    assert row.filters == {"course_slug": "dl", "week": 3}
    assert row.status == "ok"
    assert row.conversation_id == "conv-1"


def test_failures_are_logged(db_session, monkeypatch):
    monkeypatch.setattr(query_logs, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    query_logs.log_failure(
        endpoint="chat",
        question="x",
        filters=None,
        top_k=8,
        error="qdrant down",
        conversation_id=None,
    )

    row = db_session.query(QueryLog).one()
    assert row.status == "error"
    assert "qdrant" in row.error
