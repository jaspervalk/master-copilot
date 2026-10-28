import io
import json

from app.eval.search import api_search, hits_from_results, known_paths_api, known_paths_in_process
from app.models import Document


def test_hits_from_api_results_keep_path_pages_and_score():
    results = [
        {"source_path": "a.pdf", "page_start": 10, "page_end": 12, "score": 0.61, "text": "..."},
        {"source_path": "b.pdf", "page_start": 3, "page_end": 3, "score": 0.0},
    ]

    hits = hits_from_results(results)

    assert hits[0].source_path == "a.pdf"
    assert (hits[0].page_start, hits[0].page_end, hits[0].score) == (10, 12, 0.61)
    assert hits[1].score == 0.0


def _fake_opener(responses: dict[str, object]):
    """Beantwoordt urlopen(request) met vaste JSON per pad; registreert de body."""
    calls = []

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def opener(request, timeout=None):
        path = request.full_url.split("localhost:8000", 1)[1]
        body = json.loads(request.data) if request.data else None
        calls.append((request.get_method(), path, body))
        return _Response(json.dumps(responses[path]).encode())

    opener.calls = calls
    return opener


def test_api_search_posts_question_filter_and_top_k():
    opener = _fake_opener({"/api/query": {"results": [
        {"source_path": "a.pdf", "page_start": 1, "page_end": 1, "score": 0.5}
    ]}})
    search = api_search("http://localhost:8000", mode="dense", opener=opener)

    hits = search("hoe werkt k-fold?", "sso", 5)

    method, path, body = opener.calls[0]
    assert (method, path) == ("POST", "/api/query")
    assert body == {"question": "hoe werkt k-fold?", "top_k": 5,
                    "filters": {"course_slug": "sso"}, "retrieval_mode": "dense"}
    assert hits[0].source_path == "a.pdf"


def test_api_search_without_course_sends_no_filter():
    opener = _fake_opener({"/api/query": {"results": []}})
    search = api_search("http://localhost:8000", mode="hybrid", opener=opener)

    search("vraag", None, 3)

    assert opener.calls[0][2]["filters"] is None


def test_known_paths_api_reads_document_list():
    opener = _fake_opener({"/api/documents": [{"source_path": "a.pdf"}, {"source_path": "b.pdf"}]})

    assert known_paths_api("http://localhost:8000", opener=opener) == {"a.pdf", "b.pdf"}


def test_known_paths_in_process_reads_documents_table(db_session):
    db_session.add(Document(title="t", source_path="sso/books/x.pdf", checksum="0" * 64,
                            course_slug="sso", doc_kind="book"))
    db_session.commit()

    assert known_paths_in_process(db_session) == {"sso/books/x.pdf"}
