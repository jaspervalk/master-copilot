from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass

from app.core.config import settings

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None


logger = logging.getLogger(__name__)


@dataclass
class EmbeddingBatch:
    provider: str
    model: str
    dimensions: int
    vectors: list[list[float]]


class EmbeddingError(RuntimeError):
    """Raised when the configured embedding provider fails.

    Deliberately not caught inside the service — silent fallback can poison a
    collection with vectors from a different provider.
    """


class LocalHashingEmbedder:
    provider = "local-hash"
    model = "md5-bucket"

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def embed_many(self, texts: list[str]) -> EmbeddingBatch:
        return EmbeddingBatch(
            provider=self.provider,
            model=self.model,
            dimensions=self.dimensions,
            vectors=[self._embed(text) for text in texts],
        )

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"\b\w+\b", text.lower())
        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def estimate_tokens(text: str) -> int:
    """Ruwe bovengrens op het aantal tokens, zonder tiktoken als afhankelijkheid.

    Drie tekens per token overschat voor Nederlands en Engels; dat is precies de
    bedoeling. Onderschatten kost een geweigerde request halverwege een boek,
    overschatten kost hooguit een extra aanroep.
    """
    return len(text) // 3 + 1


def token_batches(
    texts: list[str],
    *,
    max_tokens: int,
    max_inputs: int,
) -> list[list[str]]:
    """Knip de invoer in stukken die binnen één embeddingrequest passen.

    Een enkele tekst die op zichzelf al over de grens gaat krijgt een eigen
    request: afkappen zou stilletjes bewijs weggooien.
    """
    batches: list[list[str]] = []
    current: list[str] = []
    tokens = 0

    for text in texts:
        cost = estimate_tokens(text)
        if current and (len(current) >= max_inputs or tokens + cost > max_tokens):
            batches.append(current)
            current, tokens = [], 0
        current.append(text)
        tokens += cost

    if current:
        batches.append(current)
    return batches


class EmbeddingService:
    def __init__(self) -> None:
        self.local_embedder = LocalHashingEmbedder(settings.local_embedding_dimensions)
        self.client = None
        if settings.openai_api_key and OpenAI is not None:
            self.client = OpenAI(api_key=settings.openai_api_key)

    @property
    def configured_provider(self) -> str:
        return "openai" if self.client is not None else self.local_embedder.provider

    @property
    def configured_model(self) -> str:
        return settings.openai_embedding_model if self.client is not None else self.local_embedder.model

    def embed_many(self, texts: list[str]) -> EmbeddingBatch:
        if not texts:
            return EmbeddingBatch(
                provider=self.configured_provider,
                model=self.configured_model,
                dimensions=0,
                vectors=[],
            )

        if self.client is None:
            return self.local_embedder.embed_many(texts)

        # Strict path: with OpenAI configured, refuse to silently fall back.
        # Mid-corpus provider switching produces collections with mixed vectors
        # that look fine and retrieve garbage.
        batches = token_batches(
            texts,
            max_tokens=settings.openai_embedding_max_tokens_per_request,
            max_inputs=settings.openai_embedding_max_inputs_per_request,
        )
        if len(batches) > 1:
            logger.info("Embedden van %d teksten in %d requests", len(texts), len(batches))

        vectors: list[list[float]] = []
        for index, batch in enumerate(batches, start=1):
            try:
                request: dict[str, object] = {
                    "model": settings.openai_embedding_model,
                    "input": batch,
                }
                if settings.openai_embedding_model.startswith("text-embedding-3"):
                    request["dimensions"] = settings.openai_embedding_dimensions

                response = self.client.embeddings.create(**request)
            except Exception as exc:
                raise EmbeddingError(
                    f"OpenAI embedding call failed for model {settings.openai_embedding_model} "
                    f"(batch {index}/{len(batches)}): {exc}"
                ) from exc

            # De volgorde moet die van `texts` blijven: de aanroeper koppelt de
            # vectoren op index aan zijn chunks.
            vectors.extend(item.embedding for item in response.data)

        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"OpenAI gaf {len(vectors)} vectoren terug voor {len(texts)} teksten"
            )

        return EmbeddingBatch(
            provider="openai",
            model=settings.openai_embedding_model,
            dimensions=len(vectors[0]),
            vectors=vectors,
        )

    def embed_query(self, text: str) -> EmbeddingBatch:
        return self.embed_many([text])
