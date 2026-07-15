from __future__ import annotations

import httpx

from recall.errors import EmbedderUnreachableError

# nomic-embed-text is asymmetric. These prefixes are part of the model's contract.
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

KNOWN_DIMS = {"nomic-embed-text": 768}
DEFAULT_TIMEOUT = 300.0  # CPU-only boxes are slow; a timeout here is not an error.


class OllamaEmbedder:
    def __init__(
        self,
        model: str = "nomic-embed-text",
        endpoint: str = "http://localhost:11434",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.name = f"ollama:{model}"
        self.dim = KNOWN_DIMS.get(model, 768)
        self._timeout = timeout

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        url = f"{self.endpoint}/api/embed"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json={"model": self.model, "input": inputs})
        except httpx.HTTPError as exc:
            raise EmbedderUnreachableError(
                f"Cannot reach Ollama at {self.endpoint} ({exc}).\n"
                f"Is it running? Start it with:  ollama serve\n"
                f"Then pull the model with:      ollama pull {self.model}\n"
                f"recall will not fall back to a different model: a vector from the "
                f"wrong model is meaningless against the ones already stored."
            ) from exc

        if response.status_code != 200:
            raise EmbedderUnreachableError(
                f"Ollama at {self.endpoint} returned {response.status_code}: "
                f"{response.text.strip()}\n"
                f"If the model is missing, pull it with:  ollama pull {self.model}\n"
                f"recall will not fall back to a different model."
            )

        embeddings = response.json().get("embeddings")
        if not embeddings:
            raise EmbedderUnreachableError(
                f"Ollama at {self.endpoint} returned no embeddings for model "
                f"{self.model!r}. Check:  ollama pull {self.model}"
            )
        return embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed([f"{DOCUMENT_PREFIX}{t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([f"{QUERY_PREFIX}{text}"])[0]
