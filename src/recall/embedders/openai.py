from __future__ import annotations

import os

import httpx

from recall.errors import EmbedderUnreachableError

KNOWN_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}


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
    ) -> None:
        self.model = model
        self.name = f"openai:{model}"
        self.dim = KNOWN_DIMS.get(model, 1536)
        self.endpoint = endpoint.rstrip("/")
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._timeout = timeout

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        if not self._api_key:
            raise EmbedderUnreachableError(
                "No OpenAI API key. Set OPENAI_API_KEY, or switch to the local "
                "default with:  recall config set embedding.provider ollama\n"
                "Note that the OpenAI embedder sends your content off this machine."
            )
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

        if response.status_code != 200:
            raise EmbedderUnreachableError(
                f"OpenAI returned {response.status_code}: {response.text.strip()}"
            )

        data = sorted(response.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts) if texts else []

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]
