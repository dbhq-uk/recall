from datetime import datetime

import pytest

from recall.mcp_server import recall_search, recall_sources, recall_status, resolve_current_source
from tests.conftest import TEST_DSN, requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    import recall.mcp_server as m

    monkeypatch.setenv("RECALL_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("RECALL_DATABASE_URL", TEST_DSN)
    # A cached _store_cache/_embedder_cache from an earlier test (one that
    # didn't monkeypatch _store/build_embedder) must never leak into this one.
    m.reset_caches()


@pytest.fixture
def indexed(store_factory, tmp_path, monkeypatch):
    from recall.config import Registry
    from recall.indexer import index_source
    from tests.support.fake_embedder import FakeEmbedder

    root = tmp_path / "brain"
    root.mkdir()
    (root / ".recall.toml").write_text('[source]\ntag = "brain"\ninclude = ["**/*.md"]\n')
    (root / "van.md").write_text("# Van\n\n" + ("we fitted a pop-top roof for headroom. " * 12))
    Registry.load().register(root)

    store = store_factory(dim=8)
    emb = FakeEmbedder(dim=8)
    index_source("brain", registry=Registry.load(), store=store, embedder=emb)

    monkeypatch.setattr("recall.mcp_server.build_embedder", lambda cfg: emb)
    monkeypatch.setattr("recall.mcp_server._store", lambda: store)
    return root


def test_resolve_current_source_prefers_the_explicit_flag(tmp_path):
    assert resolve_current_source(cwd=tmp_path, explicit="dbhq") == "dbhq"


def test_resolve_current_source_walks_up_for_a_marker(tmp_path):
    root = tmp_path / "brain"
    (root / "nested").mkdir(parents=True)
    (root / ".recall.toml").write_text('[source]\ntag = "brain"\n')
    assert resolve_current_source(cwd=root / "nested", explicit=None) == "brain"


def test_resolve_current_source_errors_when_it_cannot_tell(tmp_path):
    from recall.errors import ConfigError

    with pytest.raises(ConfigError, match="--source"):
        resolve_current_source(cwd=tmp_path, explicit=None)


def test_search_returns_hits(indexed):
    out = recall_search(query="pop-top roof", sources=["brain"], limit=5)
    assert out["results"]
    assert out["results"][0]["rel_path"] == "van.md"


def test_SEARCH_RESPONSE_DECLARES_WHICH_RANKER_IS_LIVE(indexed):
    """The agent must know what it is holding."""
    out = recall_search(query="pop-top", sources=["brain"], limit=5)
    assert out["retrieval"]["lexical_ranker"] in ("bm25", "ts_rank_cd")
    assert "hybrid" in out["retrieval"]


def test_SEARCH_RESPONSE_ADMITS_WHEN_IT_IS_DENSE_ONLY(indexed):
    """Design §Failure modes: never present a dense-only result as a hybrid one."""
    out = recall_search(query="zzzznotawordanywhere", sources=["brain"], limit=5)
    assert out["retrieval"]["hybrid"] is False
    assert any("dense-only" in n for n in out["retrieval"]["notes"])


def test_search_response_reports_the_fusion_policy(indexed):
    """Weighted fusion is a policy decision made in config, not the store's
    default. The agent must be able to see the fusion policy in force."""
    from recall.config import load_config

    config = load_config()
    out = recall_search(query="pop-top roof", sources=["brain"], limit=5)
    assert out["retrieval"]["rrf_k"] == config.rrf_k
    assert out["retrieval"]["weight_dense"] == config.fusion_weight_dense
    assert out["retrieval"]["weight_lexical"] == config.fusion_weight_lexical


def test_search_defaults_to_the_current_silo(indexed, monkeypatch):
    monkeypatch.setattr("recall.mcp_server.CURRENT_SOURCE", "brain")
    out = recall_search(query="pop-top", sources=None, limit=5)
    assert {r["source"] for r in out["results"]} == {"brain"}


def test_search_results_carry_the_heading_trail(indexed):
    out = recall_search(query="pop-top roof", sources=["brain"], limit=5)
    assert out["results"][0]["context"] == "Van"


def test_sources_lists_tag_chunk_count_and_last_indexed(indexed):
    out = recall_sources()
    assert out["sources"][0]["tag"] == "brain"
    assert out["sources"][0]["chunks"] > 0
    last_indexed = out["sources"][0]["last_indexed"]
    assert last_indexed is not None
    # ISO-8601 round-trips; that's the contract the agent on the other end relies on.
    datetime.fromisoformat(last_indexed)


def test_status_reports_ranker_model_dim_and_backend(indexed):
    out = recall_status()
    assert out["lexical_ranker"] in ("bm25", "ts_rank_cd")
    assert out["embedding_model"]
    assert out["embedding_dim"] > 0
    assert out["backend"] == "pgvector"


def test_STATUS_WARNS_ON_THE_FALLBACK_RANKER(store_factory, tmp_path, monkeypatch):
    """recall_status reports the ranker so the agent knows what it is holding."""
    store = store_factory(dim=8, pg_search_enabled=False)
    monkeypatch.setattr("recall.mcp_server._store", lambda: store)
    out = recall_status()
    assert out["lexical_ranker"] == "ts_rank_cd"
    assert any("not BM25" in w for w in out["warnings"])


def test_search_rejects_a_zero_limit(indexed):
    from recall.errors import InvalidLimitError

    with pytest.raises(InvalidLimitError, match="0"):
        recall_search(query="pop-top", sources=["brain"], limit=0)


def test_search_rejects_a_negative_limit(indexed):
    from recall.errors import InvalidLimitError

    with pytest.raises(InvalidLimitError, match="-1"):
        recall_search(query="pop-top", sources=["brain"], limit=-1)


def test_search_rejects_a_limit_above_the_maximum(indexed):
    from recall.errors import InvalidLimitError
    from recall.store.pgvector import PgVectorStore

    too_big = PgVectorStore.MAX_LIMIT + 1
    with pytest.raises(InvalidLimitError, match=str(too_big)):
        recall_search(query="pop-top", sources=["brain"], limit=too_big)


def test_status_reports_last_indexed_per_source(indexed):
    out = recall_status()
    assert "last_indexed" in out
    assert out["last_indexed"]["brain"] is not None
    datetime.fromisoformat(out["last_indexed"]["brain"])


def test_status_warns_when_a_registered_source_has_never_been_indexed(
    store_factory, tmp_path, monkeypatch
):
    """A registered source with no chunks yet must not look silently healthy."""
    from recall.config import Registry

    store = store_factory(dim=8)
    monkeypatch.setattr("recall.mcp_server._store", lambda: store)

    root = tmp_path / "ghost"
    root.mkdir()
    (root / ".recall.toml").write_text('[source]\ntag = "ghost"\n')
    Registry.load().register(root)

    out = recall_status()
    assert out["last_indexed"] == {}
    assert any("ghost" in w and "never" in w for w in out["warnings"])


def test_indexing_is_NOT_exposed_as_a_tool():
    """Design: indexing is slow and mutating. An agent should not be able to kick
    one off in the middle of a conversation."""
    import recall.mcp_server as m

    exposed = {n for n in dir(m) if n.startswith("recall_")}
    assert exposed == {"recall_search", "recall_sources", "recall_status"}
