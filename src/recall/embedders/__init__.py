from __future__ import annotations

from typing import Protocol, runtime_checkable

from recall.config import RecallConfig
from recall.errors import ConfigError, RecallError

# Defensive caps on a single HTTP request to an embedding backend. indexer.py
# batches up to EMBED_BATCH=64 chunks of up to MAX_CHUNK_CHARS=2000 chars each
# before calling embed_documents — that is up to ~128,000 chars in one call,
# which can exceed a provider's per-request item or token limits (OpenAI caps
# /embeddings at 2048 input items and a total-token budget well under what
# 64 * 2000-char chunks can reach). These numbers are deliberately
# conservative estimates, not an exact enforcement of any one provider's
# limits — if a request is still rejected as oversize, that surfaces as
# EmbedderRequestRejectedError rather than a silent truncation or a wrong
# model substitution.
DEFAULT_MAX_BATCH_ITEMS = 200
DEFAULT_MAX_BATCH_CHARS = 100_000


class EmbedderRequestRejectedError(RecallError):
    """The embedding backend rejected a request outright (HTTP 400/413),
    distinct from EmbedderUnreachableError (the endpoint could not be reached
    at all). Typically means the request — even after our own defensive
    batch-splitting — was still too large for the backend's own limits.
    """


def batch_by_size(
    texts: list[str],
    max_items: int = DEFAULT_MAX_BATCH_ITEMS,
    max_chars: int = DEFAULT_MAX_BATCH_CHARS,
) -> list[list[str]]:
    """Split `texts` into ordered sub-lists, each under the item/char caps.

    Order is preserved both within and across batches — callers concatenate
    the per-batch results back into one list and rely on that order matching
    the input exactly (see the embedders' embed_documents).

    A single text longer than max_chars gets a batch of its own rather than
    being split mid-text (splitting an embedding input would change its
    meaning); if the backend still rejects it, that surfaces as
    EmbedderRequestRejectedError rather than corrupting the text.
    """
    batches: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for text in texts:
        if current and (len(current) >= max_items or current_chars + len(text) > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(text)
        current_chars += len(text)
    if current:
        batches.append(current)
    return batches


@runtime_checkable
class Embedder(Protocol):
    """Documents and queries get separate methods ON PURPOSE.

    Several strong local models are asymmetric and want a task prefix
    (search_document: vs search_query:). Collapsing these into one embed() is a
    quiet correctness bug: it costs retrieval quality and is invisible at query
    time, because nothing errors — the vectors are simply in the wrong place.
    """

    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def build_embedder(config: RecallConfig) -> Embedder:
    from recall.embedders.ollama import OllamaEmbedder
    from recall.embedders.openai import OpenAIEmbedder

    provider = config.embedding_provider
    if provider == "ollama":
        return OllamaEmbedder(
            model=config.embedding_model,
            endpoint=config.embedding_endpoint,
            timeout=config.embedding_timeout,
        )
    if provider == "openai":
        return OpenAIEmbedder(model=config.embedding_model, timeout=config.embedding_timeout)
    raise ConfigError(
        f"Unknown embedding provider {provider!r}. v1 supports: ollama, openai. "
        f"(Voyage and Gemini come later, behind the same interface.)"
    )
