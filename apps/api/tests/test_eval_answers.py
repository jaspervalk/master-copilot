import io
import json

from app.eval.answers import AnswerOutcome, api_answer, mentions_ok


def test_mentions_ok_is_case_insensitive_substring_match():
    assert mentions_ok("De L1-penalty zet coëfficiënten op nul.", ["l1-penalty", "nul"]) is True
    assert mentions_ok("Ridge gebruikt L2.", ["lasso"]) is False


def test_mentions_ok_is_not_applicable_without_a_list():
    assert mentions_ok("tekst", []) is None


def test_api_answer_posts_to_chat_and_maps_the_response():
    calls = []

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def opener(request, timeout=None):
        calls.append((request.full_url, json.loads(request.data)))
        return _Response(json.dumps({
            "answer": "Ridge krimpt.", "abstained": False, "confidence": "high", "latency_ms": 812,
        }).encode())

    answer = api_answer("http://localhost:8000", mode="hybrid", opener=opener)

    outcome = answer("wat is ridge?", "sso", 6, {"document_id": "d1", "reveal": False})

    assert calls[0][0].endswith("/api/chat")
    assert calls[0][1]["filters"] == {"course_slug": "sso"}
    assert calls[0][1]["answer_style"] == "short"
    assert calls[0][1]["coach"] == {"document_id": "d1", "reveal": False}
    assert outcome == AnswerOutcome(text="Ridge krimpt.", abstained=False, confidence="high", latency_ms=812)


def test_leaked_terms_finds_forbidden_substrings():
    from app.eval.answers import leaked_terms

    assert leaked_terms("De variance is 2.92, dus np(1-p).", ["2.92", "np(1-p)", "geheim"]) == ["2.92", "np(1-p)"]
    assert leaked_terms("alleen een hint", ["2.92"]) == []
