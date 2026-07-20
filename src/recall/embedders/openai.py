from __future__ import annotations

import os
import warnings

import httpx

from recall.embedders import (
    DEFAULT_MAX_BATCH_CHARS,
    DEFAULT_MAX_BATCH_ITEMS,
    EmbedderRequestRejectedError,
    batch_by_size,
)
from recall.errors import EmbedderUnreachableError

KNOWN_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}

# Same split as ollama.py: 400/413/422 means the request was rejected outright
# (too large / malformed), distinct from any other failure to reach the API.
_REJECTED_STATUSES = {400, 413, 422}


class OpenAIEmbedder:
    """Symmetric: OpenAI's embedding models do not take a task prefix.

    The Embedder protocol still gives documents and queries separate methods,
    because the *interface* must accommodate asymmetric models even when a given
    implementation happens not to need it.
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        endpoint: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
        max_batch_items: int = DEFAULT_MAX_BATCH_ITEMS,
        max_batch_chars: int = DEFAULT_MAX_BATCH_CHARS,
    ) -> None:
        self.model = model
        self.name = f"openai:{model}"
        self.dim = KNOWN_DIMS.get(model, 1536)
        self.endpoint = endpoint.rstrip("/")
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._timeout = timeout
        self._warned_off_machine = False
        self._max_batch_items = max_batch_items
        self._max_batch_chars = max_batch_chars

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        if not self._api_key:
            raise EmbedderUnreachableError(
                "No OpenAI API key. Set OPENAI_API_KEY, or switch to the local "
                "default with:  recall config set embedding.provider ollama"
            )
        if not self._warned_off_machine:
            warnings.warn(
                "The OpenAI embedder sends your content to api.openai.com — it does "
                "not stay on this machine. Switch to the local default (ollama) to "
                "keep retrieval fully local.",
                stacklevel=2,
            )
            self._warned_off_machine = True
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self.endpoint}/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self.model, "input": inputs},
                )
        except httpx.HTTPError as exc:
            raise EmbedderUnreachableError(
                f"Cannot reach OpenAI at {self.endpoint} ({exc}). "
                f"recall will not fall back to a different model."
            ) from exc

        if response.status_code in _REJECTED_STATUSES:
            raise EmbedderRequestRejectedError(
                f"OpenAI rejected the request as too large or malformed "
                f"({response.status_code}): {response.text.strip()}\n"
                f"recall already splits large indexing batches, but this request "
                f"still exceeded a limit (OpenAI caps /embeddings at 2048 items and "
                f"a total-token budget per request). If this recurs, lower the "
                f"embedder's max_batch_items / max_batch_chars."
            )

        if response.status_code != 200:
            raise EmbedderUnreachableError(
                f"OpenAI returned {response.status_code}: {response.text.strip()}"
            )

        data = sorted(response.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for batch in batch_by_size(texts, self._max_batch_items, self._max_batch_chars):
            vectors.extend(self._embed(batch))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]
