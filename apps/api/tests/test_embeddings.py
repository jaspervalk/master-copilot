import pytest

from app.services.embeddings import (
    EmbeddingError,
    EmbeddingService,
    LocalHashingEmbedder,
    estimate_tokens,
    token_batches,
)


class _RaisingEmbeddings:
    def create(self, **_kwargs):
        raise RuntimeError("simulated openai outage")


class _RaisingClient:
    def __init__(self) -> None:
        self.embeddings = _RaisingEmbeddings()


def test_local_embedder_returns_provider_and_model():
    embedder = LocalHashingEmbedder(dimensions=64)

    batch = embedder.embed_many(["hello world"])

    assert batch.provider == "local-hash"
    assert batch.model == "md5-bucket"
    assert batch.dimensions == 64
    assert len(batch.vectors) == 1


def test_embedding_service_falls_back_to_local_only_when_no_openai_client():
    service = EmbeddingService()
    service.client = None

    batch = service.embed_many(["a chunk"])

    assert batch.provider == "local-hash"
    assert batch.model == "md5-bucket"


def test_embedding_service_raises_when_configured_openai_call_fails():
    """With OpenAI configured, failures must propagate — no silent local fallback."""
    service = EmbeddingService()
    service.client = _RaisingClient()

    with pytest.raises(EmbeddingError):
        service.embed_many(["a chunk"])


class _RecordingEmbeddings:
    """Registreert elke request en geeft een vector per invoer terug."""

    def __init__(self, dimensions: int = 4) -> None:
        self.calls: list[list[str]] = []
        self.dimensions = dimensions

    def create(self, **kwargs):
        inputs = list(kwargs["input"])
        self.calls.append(inputs)

        class _Item:
            def __init__(self, embedding):
                self.embedding = embedding

        class _Response:
            def __init__(self, data):
                self.data = data

        return _Response([_Item([float(index)] * self.dimensions) for index, _ in enumerate(inputs)])


class _RecordingClient:
    def __init__(self, dimensions: int = 4) -> None:
        self.embeddings = _RecordingEmbeddings(dimensions)


def test_token_batches_respects_input_cap():
    batches = token_batches(["a", "b", "c", "d", "e"], max_tokens=10_000, max_inputs=2)

    assert [len(batch) for batch in batches] == [2, 2, 1]


def test_token_batches_respects_token_budget():
    # Elke tekst schat op ~34 tokens; drie passen er in een budget van 100.
    texts = ["x" * 100 for _ in range(7)]

    batches = token_batches(texts, max_tokens=100, max_inputs=1000)

    assert all(sum(estimate_tokens(text) for text in batch) <= 100 for batch in batches)
    assert sum(len(batch) for batch in batches) == 7


def test_token_batches_keeps_oversized_text_in_its_own_request():
    """Afkappen zou stil bewijs weggooien; een te grote tekst krijgt een eigen request."""
    batches = token_batches(["klein", "x" * 10_000, "klein"], max_tokens=100, max_inputs=1000)

    assert [len(batch) for batch in batches] == [1, 1, 1]
    assert batches[1][0] == "x" * 10_000


def test_large_document_is_split_across_requests(monkeypatch: pytest.MonkeyPatch):
    """Een tekstboek gaat over de 300k-tokengrens van één OpenAI-request heen."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_embedding_max_tokens_per_request", 1_000)
    monkeypatch.setattr(settings, "openai_embedding_max_inputs_per_request", 512)

    service = EmbeddingService()
    service.client = _RecordingClient()
    texts = ["woord " * 200 for _ in range(20)]

    batch = service.embed_many(texts)

    assert len(service.client.embeddings.calls) > 1
    # Volgorde en aantal moeten intact blijven: de aanroeper koppelt op index.
    assert len(batch.vectors) == len(texts)
    assert [text for call in service.client.embeddings.calls for text in call] == texts


def test_small_document_still_takes_one_request():
    service = EmbeddingService()
    service.client = _RecordingClient()

    service.embed_many(["een korte chunk", "en nog een"])

    assert len(service.client.embeddings.calls) == 1
