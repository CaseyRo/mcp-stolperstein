"""Embedding generation — local sentence-transformers with optional API fallback."""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    async def embed(self, text: str) -> list[float] | None: ...


class LocalEmbeddings:
    """Generate embeddings using sentence-transformers in-process."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            logger.info("Loaded embedding model: %s", self._model_name)
        return self._model

    async def embed(self, text: str) -> list[float] | None:
        try:
            model = self._get_model()
            embedding = model.encode(text, normalize_embeddings=True)
            return embedding.tolist()
        except Exception:
            logger.warning("Local embedding failed", exc_info=True)
            return None


class APIEmbeddings:
    """Generate embeddings via an external HTTP API."""

    def __init__(self, api_url: str) -> None:
        self._api_url = api_url

    async def embed(self, text: str) -> list[float] | None:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self._api_url,
                    json={"input": text},
                )
                resp.raise_for_status()
                data = resp.json()
                # Support OpenAI-compatible format
                if "data" in data and len(data["data"]) > 0:
                    return data["data"][0]["embedding"]
                if "embedding" in data:
                    return data["embedding"]
                return None
        except Exception:
            logger.warning("API embedding failed", exc_info=True)
            return None


class NoOpEmbeddings:
    """Fallback that returns None — FTS5 only mode."""

    async def embed(self, text: str) -> list[float] | None:
        return None


def get_embedder() -> EmbeddingProvider:
    """Create the configured embedding provider."""
    from stolperstein.config import settings

    if settings.cq_embedding_api_url:
        logger.info("Using API embeddings: %s", settings.cq_embedding_api_url)
        return APIEmbeddings(settings.cq_embedding_api_url)

    try:
        return LocalEmbeddings(settings.cq_embedding_model)
    except Exception:
        logger.warning(
            "Failed to initialize local embeddings, falling back to FTS5 only",
            exc_info=True,
        )
        return NoOpEmbeddings()
