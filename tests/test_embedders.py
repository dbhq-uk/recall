import warnings

import httpx
import pytest

from recall.config import RecallConfig
from recall.embedders import build_embedder
from recall.embedders.ollama import OllamaEmbedder
from recall.embedders.openai import OpenAIEmbedder
from recall.errors import ConfigError, EmbedderUnreachableError
from tests.support.fake_embedder import FakeEmbedder


def test_fake_embedder_is_deterministic():
    e = FakeEmbedder(dim=8)
    assert e.embed_query("hello") == e.embed_query("hello")
    assert e.embed_query("hello") != e.embed_query("goodbye")


def test_fake_embedder_respects_its_dimension():
    assert len(FakeEmbedder(dim=16).embed_query("x")) == 16


def test_ollama_applies_ASYMMETRIC_PREFIXES(monkeypatch):
    """The design's quiet-correctness-bug warning. nomic-embed-text is asymmetric:
    documents and queries must be prefixed differently, or retrieval quality drops
    in a way that is completely invisible at query time."""
    seen: dict = {}

    def fake_post(self, url, json, **kw):
        seen["url"] = url
        seen["input"] = json["input"]
        return httpx.Response(
            200,
            json={"embeddings": [[0.1] * 768 for _ in json["input"]]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    e = OllamaEmbedder(model="nomic-embed-text", endpoint="http://localhost:11434")

    e.embed_documents(["the van has a pop-top"])
    assert seen["input"] == ["search_document: the van has a pop-top"]

    e.embed_query("how do we get headroom")
    assert seen["input"] == ["search_query: how do we get headroom"]


def test_ollama_uses_the_batch_endpoint(monkeypatch):
    seen = {}

    def fake_post(self, url, json, **kw):
        seen["url"] = url
        seen["n"] = len(json["input"])
        return httpx.Response(
            200,
            json={"embeddings": [[0.1] * 768] * len(json["input"])},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    OllamaEmbedder(model="nomic-embed-text", endpoint="http://x").embed_documents(["a", "b", "c"])
    assert seen["url"].endswith("/api/embed")
    assert seen["n"] == 3


def test_ollama_unreachable_names_the_endpoint_AND_the_fix(monkeypatch):
    """Design: hard error naming the exact endpoint and the fix. Never fall back
    to a different model."""

    def boom(self, url, json, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.Client, "post", boom)

    e = OllamaEmbedder(model="nomic-embed-text", endpoint="http://localhost:11434")
    with pytest.raises(EmbedderUnreachableError) as exc:
        e.embed_query("x")

    msg = str(exc.value)
    assert "http://localhost:11434" in msg
    assert "ollama serve" in msg
    assert "nomic-embed-text" in msg


def test_ollama_never_silently_substitutes_a_model(monkeypatch):
    """There is no fallback path. A wrong-model vector is worse than no vector."""

    def missing_model(self, url, json, **kw):
        return httpx.Response(
            404,
            json={"error": 'model "nomic-embed-text" not found'},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", missing_model)
    with pytest.raises(EmbedderUnreachableError, match="ollama pull"):
        OllamaEmbedder(model="nomic-embed-text", endpoint="http://x").embed_query("q")


def test_embedder_name_identifies_provider_and_model():
    e = OllamaEmbedder(model="nomic-embed-text", endpoint="http://x")
    assert e.name == "ollama:nomic-embed-text"


def test_build_embedder_defaults_to_ollama():
    e = build_embedder(RecallConfig())
    assert e.name == "ollama:nomic-embed-text"
    assert e.dim == 768


def test_build_embedder_rejects_an_unknown_provider():
    with pytest.raises(ConfigError, match="voyage"):
        build_embedder(RecallConfig(embedding_provider="voyage"))


def test_openai_reorders_embeddings_by_index(monkeypatch):
    """OpenAI's API may return items out of order; the code must sort by `index`
    or every vector ends up attached to the wrong text."""

    def fake_post(self, url, headers, json, **kw):
        # Return them REVERSED, with correct index fields.
        n = len(json["input"])
        data = [{"index": i, "embedding": [float(i)] * 4} for i in reversed(range(n))]
        return httpx.Response(200, json={"data": data}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    e = OpenAIEmbedder(model="text-embedding-3-small", api_key="sk-test")
    with warnings.catch_warnings():  # the off-machine warning is tested elsewhere
        warnings.simplefilter("ignore", UserWarning)
        vecs = e.embed_documents(["a", "b", "c"])
    assert vecs == [[0.0] * 4, [1.0] * 4, [2.0] * 4]  # index 0,1,2 in order


def test_openai_without_a_key_raises_and_names_the_local_alternative(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    e = OpenAIEmbedder(model="text-embedding-3-small", api_key="")
    with pytest.raises(EmbedderUnreachableError, match="ollama"):
        e.embed_query("x")


def test_openai_WARNS_when_content_actually_leaves_the_machine(monkeypatch):
    """The 'local by default' promise: a real send to OpenAI must warn. The one
    case that needs the warning is a successful send, not the no-key error."""

    def fake_post(self, url, headers, json, **kw):
        data = [{"index": i, "embedding": [0.1] * 4} for i in range(len(json["input"]))]
        return httpx.Response(200, json={"data": data}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    e = OpenAIEmbedder(model="text-embedding-3-small", api_key="sk-test")
    with pytest.warns(UserWarning, match="api.openai.com"):
        e.embed_documents(["hello"])


def test_openai_empty_documents_makes_no_call(monkeypatch):
    def boom(self, *a, **k):
        raise AssertionError("should not call the API for empty input")

    monkeypatch.setattr(httpx.Client, "post", boom)
    e = OpenAIEmbedder(model="text-embedding-3-small", api_key="sk-test")
    assert e.embed_documents([]) == []


def test_build_embedder_can_build_openai(monkeypatch):
    from recall.config import RecallConfig
    from recall.embedders import build_embedder

    e = build_embedder(
        RecallConfig(embedding_provider="openai", embedding_model="text-embedding-3-small")
    )
    assert e.name == "openai:text-embedding-3-small"


@pytest.mark.ollama
def test_REAL_ollama_returns_768_dimensions():
    """Integration. Requires a live Ollama with nomic-embed-text pulled."""
    e = OllamaEmbedder(model="nomic-embed-text", endpoint="http://localhost:11434")
    vecs = e.embed_documents(["the van has a pop-top roof", "postgres full text search"])
    assert len(vecs) == 2
    assert all(len(v) == 768 for v in vecs)
    assert len(e.embed_query("how do we get headroom")) == 768


@pytest.mark.ollama
def test_REAL_ollama_asymmetric_prefixes_produce_different_vectors():
    """Proof the prefixes are actually reaching the model."""
    e = OllamaEmbedder(model="nomic-embed-text", endpoint="http://localhost:11434")
    doc = e.embed_documents(["pop-top roof"])[0]
    qry = e.embed_query("pop-top roof")
    assert doc != qry  # same text, different task prefix -> different vector
