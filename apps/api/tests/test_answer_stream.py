import json

import pytest
from fastapi.testclient import TestClient

from app.api.routes import stream as stream_route
from app.db import get_db
from app.main import app
from app.models import Message, QueryLog
from app.schemas import AnswerResponse, QueryChunkResult
from app.services.answer_stream import AnswerFieldStreamer


def _feed_all(streamer: AnswerFieldStreamer, payload: str, size: int = 3) -> str:
    """Voer de JSON in stukjes aan, zoals de API hem ook stuurt."""
    return "".join(streamer.feed(payload[index : index + size]) for index in range(0, len(payload), size))


def test_streamer_extracts_only_the_answer_field():
    payload = json.dumps({"abstained": False, "answer": "Backprop werkt zo.", "confidence": "high"})

    assert _feed_all(AnswerFieldStreamer(), payload) == "Backprop werkt zo."


def test_streamer_handles_escapes_across_chunk_boundaries():
    payload = json.dumps({"answer": 'regel1\nregel2 "geciteerd" en \\ terug'})

    assert _feed_all(AnswerFieldStreamer(), payload, size=1) == 'regel1\nregel2 "geciteerd" en \\ terug'


def test_streamer_handles_unicode_escapes():
    payload = '{"answer": "caf\\u00e9"}'

    assert _feed_all(AnswerFieldStreamer(), payload, size=2) == "café"


def test_streamer_stops_after_the_closing_quote():
    payload = json.dumps({"answer": "klaar", "confidence_reasons": ["answer bevat dit niet"]})
    streamer = AnswerFieldStreamer()

    result = _feed_all(streamer, payload)

    assert result == "klaar"
    assert streamer.is_done


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
    """Zonder OpenAI-sleutel valt de stream terug op het extractieve pad."""

    def __init__(self) -> None:
        self.client = None

    def retrieve(self, question, top_k, filters=None, mode="hybrid"):
        return "local-hash", [_chunk()]

    def compose_from_chunks(self, *, question, retrieval_query, chunks, provider, style, coach=None, language="auto"):
        return AnswerResponse(
            question=question,
            rewritten_query=retrieval_query,
            answer="Uitleg over backprop [1]",
            abstained=False,
            confidence="medium",
            confidence_reasons=["1 fragment opgehaald."],
            citations=[],
            retrieved_chunks=chunks,
            embedding_provider=provider,
            answer_model="local-extractive",
            answer_style=style,
        )


@pytest.fixture()
def client(db_session, monkeypatch):
    fake = _FakeAnswering()
    monkeypatch.setattr(stream_route, "AnsweringService", lambda: fake)
    monkeypatch.setattr("app.services.answer_stream.AnsweringService", lambda: fake)
    monkeypatch.setattr("app.services.answer_stream._async_client", lambda: None)
    monkeypatch.setattr(stream_route.query_logs, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _events(response) -> list[dict]:
    frames = []
    for block in response.text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                frames.append(json.loads(line[5:].strip()))
    return frames


def test_stream_emits_retrieval_then_deltas_then_complete(client):
    response = client.post("/api/chat/stream", json={"question": "Wat is backprop?"})

    assert response.status_code == 200
    events = _events(response)
    assert events[0]["type"] == "retrieval"
    assert events[0]["conversation_id"]
    assert events[0]["chunks"][0]["chunk_id"] == "chunk-1"
    assert any(event["type"] == "answer_delta" for event in events)
    assert events[-1]["type"] == "complete"
    assert events[-1]["answer"] == "Uitleg over backprop [1]"


def test_stream_records_the_turn_and_logs_it(client, db_session):
    client.post("/api/chat/stream", json={"question": "Wat is backprop?"})

    assert db_session.query(Message).count() == 2
    row = db_session.query(QueryLog).one()
    assert row.endpoint == "stream"
    assert row.status == "ok"


def test_stream_reuses_an_existing_conversation(client, db_session):
    first = _events(client.post("/api/chat/stream", json={"question": "Wat is backprop?"}))[0]

    second = _events(
        client.post(
            "/api/chat/stream",
            json={"question": "En waarom werkt dat?", "conversation_id": first["conversation_id"]},
        )
    )[0]

    assert second["conversation_id"] == first["conversation_id"]
    assert db_session.query(Message).count() == 4


def test_delta_repairer_fixes_escaped_newline_within_one_delta():
    """Een afsluitend commando-achtig stuk blijft hangen tot flush: dat is het contract."""
    from app.services.answer_stream import DeltaTextRepairer

    repairer = DeltaTextRepairer()

    eerste = repairer.feed(r"geldt:\n\nDit")

    assert eerste == "geldt:\n"
    assert eerste + repairer.flush() == "geldt:\n\nDit"


def test_delta_repairer_holds_back_a_split_escape():
    """De backslash en de n komen in verschillende deltas binnen."""
    from app.services.answer_stream import DeltaTextRepairer

    repairer = DeltaTextRepairer()

    assert repairer.feed("geldt:\\") == "geldt:"
    assert repairer.feed("nDit ") == "\nDit "
    assert repairer.flush() == ""


def test_delta_repairer_waits_before_breaking_a_latex_command():
    """`\\n` mag pas een newline worden als het volgende teken geen letter is."""
    from app.services.answer_stream import DeltaTextRepairer

    repairer = DeltaTextRepairer()

    assert repairer.feed(r"de gradient \n") == "de gradient "
    assert repairer.feed("abla f") == r"\nabla f"
    assert repairer.flush() == ""


def test_delta_repairer_keeps_a_command_split_deep_in_the_word():
    """`\\nab` + `la` is nog steeds `\\nabla`, geen regelovergang plus \'abla\'."""
    from app.services.answer_stream import DeltaTextRepairer

    repairer = DeltaTextRepairer()

    assert repairer.feed(r"gradient \nab") == "gradient "
    assert repairer.feed("la f = 0") == r"\nabla f = 0"


def test_delta_repairer_flushes_a_trailing_escape_at_the_end():
    from app.services.answer_stream import DeltaTextRepairer

    repairer = DeltaTextRepairer()

    assert repairer.feed(r"einde\n") == "einde"
    assert repairer.flush() == "\n"


def test_delta_repairer_concatenation_matches_whole_text_normalisation():
    """Stuk voor stuk voeren moet hetzelfde opleveren als het hele antwoord ineens."""
    from app.services.answer_stream import DeltaTextRepairer
    from app.services.answering import normalize_answer_text

    volledig = r"Var$=\ell^T C \ell$.\n\nMet \nabla f \neq 0 volgt:\n\[x\]\n"

    for grootte in (1, 2, 3, 7):
        repairer = DeltaTextRepairer()
        stukken = [volledig[i : i + grootte] for i in range(0, len(volledig), grootte)]
        uit = "".join(repairer.feed(stuk) for stuk in stukken) + repairer.flush()
        assert uit == normalize_answer_text(volledig), f"stukgrootte {grootte}"
