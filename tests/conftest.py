import os

import pytest

TEST_DSN = os.environ.get(
    "RECALL_TEST_DATABASE_URL", "postgresql://recall@localhost:5432/recall_test"
)


def _postgres_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(TEST_DSN, connect_timeout=3):
            return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_available(),
    reason=f"no Postgres at {TEST_DSN} (set RECALL_TEST_DATABASE_URL)",
)


@pytest.fixture
def store_factory():
    """Build a PgVectorStore against the test DB with a freshly dropped schema.

    Pass pg_search_enabled=False to get a genuinely pg_search-free store — no bm25
    index, ts_rank_cd queries — which is how we prove the fallback is honest even
    on a machine that HAS pg_search.
    """
    from recall.store.pgvector import PgVectorStore

    created = []

    def _make(dim: int = 8, model: str = "fake:fake", provider: str = "fake", *, pg_search_enabled=None):
        store = PgVectorStore(TEST_DSN, pg_search_enabled=pg_search_enabled)
        store.drop_all()
        store.init(dim=dim, model=model, provider=provider)
        created.append(store)
        return store

    yield _make

    for store in created:
        store.drop_all()
