from __future__ import annotations

import hashlib


class FakeEmbedder:
    """Deterministic, offline, and asymmetric — like the real thing.

    Vectors are derived from a hash of the text, so identical text always yields
    an identical vector and different text yields a different one. That is all a
    unit test needs; it says nothing about retrieval quality, which is precisely
    what the golden harness is for.
    """

    def __init__(self, dim: int = 8, model: str = "fake") -> None:
        self.dim = dim
        self.name = f"fake:{model}"

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [digest[i % len(digest)] / 255.0 for i in range(self.dim)]
        norm = sum(v * v for v in raw) ** 0.5 or 1.0
        return [v / norm for v in raw]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(f"search_document: {t}") for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(f"search_query: {text}")
