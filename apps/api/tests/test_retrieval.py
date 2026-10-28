import pytest

from app.schemas import QueryFilters
from app.services.qdrant_index import SearchHit
from app.services.retrieval import RetrievalService


class _FakeEmbeddings:
    def embed_query(self, text: str):
        class _Batch:
            vectors = [[0.1, 0.2, 0.3]]
            provider = "local-hash"
            model = "local"
            dimensions = 3

        return _Batch()


class _FakeIndex:
    def __init__(self, hits):
        self._hits = hits
        self.last_filters = None

    def search(self, vector, limit, filters=None, hidden=None, week_spans=None):
        self.last_filters = filters
        self.last_hidden = hidden
        return self._hits[:limit]

    def retrieve_payloads(self, chunk_ids):
        return []


class _FakeSparse:
    def __init__(self, results):
        self._results = results
        self.ready = True
        self.last_filters = None

    def search(self, query, limit, filters=None, hidden=None, week_spans=None):
        self.last_filters = filters
        self.last_hidden = hidden
        return self._results[:limit]


def _hit(chunk_id: str, score: float) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        score=score,
        payload={
            "document_id": "doc-1",
            "document_title": "Bishop",
            "source_path": "dl/books/bishop.pdf",
            "course_slug": "dl",
            "doc_kind": "book",
            "week": None,
            "assignment_status": None,
            "section_path": "5 Neural Networks",
            "page_start": 10,
            "page_end": 11,
            "text": "backpropagation",
            "chunk_metadata": {},
        },
    )


@pytest.fixture()
def service():
    def _build(dense_hits, sparse_results):
        retrieval = RetrievalService.__new__(RetrievalService)
        retrieval.embedding_service = _FakeEmbeddings()
        retrieval.index_service = _FakeIndex(dense_hits)
        retrieval._sparse = _FakeSparse(sparse_results)
        # Deze tests bouwen de service zonder __init__; zonder provider zou
        # `search` de echte database openen om open weken te bepalen.
        retrieval._hidden_weeks = lambda: {}
        retrieval._week_spans = lambda course, week: []
        return retrieval

    return _build


def test_dense_mode_returns_mapped_results(service):
    retrieval = service([_hit("a", 0.9), _hit("b", 0.5)], [])

    provider, results = retrieval.search("backprop", top_k=2, mode="dense")

    assert provider == "local-hash"
    assert [result.chunk_id for result in results] == ["a", "b"]
    assert results[0].course_slug == "dl"
    assert results[0].section_path == "5 Neural Networks"


def test_hybrid_passes_the_same_filters_to_both_branches(service):
    retrieval = service([_hit("a", 0.9)], [("a", 3.0)])
    filters = QueryFilters(course_slug="dl", week=3)

    retrieval.search("backprop", top_k=5, filters=filters, mode="hybrid")

    assert retrieval.index_service.last_filters == filters
    assert retrieval._sparse.last_filters == filters


def test_hybrid_keeps_a_sparse_only_hit(service):
    retrieval = service([_hit("dense-1", 0.9)], [("sparse-1", 5.0)])
    retrieval.index_service.retrieve_payloads = lambda chunk_ids: [_hit(chunk_ids[0], 0.0)]

    _provider, results = retrieval.search("elbo", top_k=5, mode="hybrid")

    assert {result.chunk_id for result in results} == {"dense-1", "sparse-1"}


def test_hybrid_falls_back_to_dense_when_sparse_is_empty(service):
    retrieval = service([_hit("a", 0.9)], [])

    _provider, results = retrieval.search("backprop", top_k=5, mode="hybrid")

    assert [result.chunk_id for result in results] == ["a"]


def test_top_k_is_respected(service):
    retrieval = service([_hit(str(index), 0.9 - index / 100) for index in range(10)], [])

    _provider, results = retrieval.search("x", top_k=3, mode="dense")

    assert len(results) == 3


def test_hidden_weeks_reach_both_branches(monkeypatch):
    from app.schemas import QueryFilters
    from app.services import retrieval as retrieval_module
    from app.services.embeddings import EmbeddingBatch

    seen = {}

    class _Dense:
        collection_name = "t"

        def search(self, vector, limit, filters=None, hidden=None, week_spans=None):
            seen["dense"] = hidden
            return []

        def retrieve_payloads(self, ids):
            return []

    class _Sparse:
        ready = True

        def search(self, query, limit, filters=None, hidden=None, week_spans=None):
            seen["sparse"] = hidden
            return []

    class _Embedder:
        def embed_query(self, text):
            return EmbeddingBatch(provider="local-hash", model="m", dimensions=2, vectors=[[0.0, 1.0]])

    monkeypatch.setattr(retrieval_module, "EmbeddingService", lambda: _Embedder())
    monkeypatch.setattr(retrieval_module, "QdrantIndexService", lambda: _Dense())
    monkeypatch.setattr(retrieval_module, "get_hybrid_index", lambda: _Sparse())

    service = retrieval_module.RetrievalService(hidden_weeks_provider=lambda: {"sso": {4}})
    service.search("ridge", top_k=3, filters=QueryFilters(course_slug="sso"))

    assert seen == {"dense": {"sso": {4}}, "sparse": {"sso": {4}}}
