from __future__ import annotations

from typing import Protocol, runtime_checkable

from recall.config import RecallConfig


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
        return OllamaEmbedder(model=config.embedding_model, endpoint=config.embedding_endpoint)
    if provider == "openai":
        return OpenAIEmbedder(model=config.embedding_model)
    raise ValueError(
        f"Unknown embedding provider {provider!r}. v1 supports: ollama, openai. "
        f"(Voyage and Gemini come later, behind the same interface.)"
    )
