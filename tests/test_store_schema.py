import psycopg
import pytest

from recall.errors import DimensionMismatchError
from tests.conftest import TEST_DSN, requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]


def _indexes(dsn: str) -> set[str]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'")
        return {r[0] for r in cur.fetchall()}


def test_init_creates_the_chunks_and_meta_tables(store_factory):
    store = store_factory()
    with psycopg.connect(TEST_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.chunks'), to_regclass('public.meta')")
        chunks, meta = cur.fetchone()
    assert chunks is not None and meta is not None


def test_init_records_the_embedding_model_in_meta(store_factory):
    store_factory(dim=8, model="fake:fake", provider="fake")
    with psycopg.connect(TEST_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT key, value FROM meta")
        meta = dict(cur.fetchall())
    assert meta["embedding_model"] == "fake:fake"
    assert meta["embedding_dim"] == "8"
    assert meta["embedding_provider"] == "fake"
    assert "schema_version" in meta


def test_init_creates_the_hnsw_and_gin_indexes(store_factory):
    store_factory()
    idx = _indexes(TEST_DSN)
    assert "chunks_embedding_idx" in idx
    assert "chunks_tsv_idx" in idx


def test_init_creates_the_bm25_index_when_pg_search_is_enabled(store_factory):
    store_factory(pg_search_enabled=True)
    assert "chunks_bm25_idx" in _indexes(TEST_DSN)


def test_init_creates_NO_bm25_index_when_pg_search_is_absent(store_factory):
    store_factory(pg_search_enabled=False)
    assert "chunks_bm25_idx" not in _indexes(TEST_DSN)
    # The tsv fallback must still be there — it IS the fallback.
    assert "chunks_tsv_idx" in _indexes(TEST_DSN)


def test_lexical_ranker_reports_bm25_when_pg_search_is_live(store_factory):
    store = store_factory(pg_search_enabled=True)
    assert store.lexical_ranker() == "bm25"


def test_lexical_ranker_HONESTLY_reports_the_fallback(store_factory):
    """The whole point of the product. If it is not BM25, say it is not BM25."""
    store = store_factory(pg_search_enabled=False)
    assert store.lexical_ranker() == "ts_rank_cd"


def test_lexical_ranker_does_not_claim_bm25_without_the_index(store_factory):
    """pg_search installed AFTER init: extension present, index absent.

    Claiming BM25 here would be exactly the silent lie recall exists to prevent.
    """
    store = store_factory(pg_search_enabled=False)
    store._pg_search_enabled = True  # simulate: extension appears later
    assert store.lexical_ranker() == "ts_rank_cd"


def test_check_model_accepts_a_match(store_factory):
    store = store_factory(dim=8, model="fake:fake")
    store.check_model("fake:fake", 8)  # must not raise


def test_check_model_HARD_ERRORS_on_a_dimension_mismatch(store_factory):
    """Design: refuse to index rather than write a corrupt index."""
    store = store_factory(dim=8, model="fake:fake")
    with pytest.raises(DimensionMismatchError, match="reindex"):
        store.check_model("fake:fake", 768)


def test_check_model_HARD_ERRORS_on_a_model_change(store_factory):
    """A vector column has one fixed width, so the model is fixed for the life of
    the database. Same dim, different model is still corrupt."""
    store = store_factory(dim=8, model="fake:fake")
    with pytest.raises(DimensionMismatchError):
        store.check_model("ollama:nomic-embed-text", 8)


def test_unique_constraint_on_source_relpath_chunkidx(store_factory):
    store_factory()
    with psycopg.connect(TEST_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'chunks'::regclass AND contype = 'u'
        """)
        assert cur.fetchall(), "chunks needs UNIQUE (source, rel_path, chunk_idx)"
