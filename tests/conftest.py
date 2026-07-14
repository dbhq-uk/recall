import os

import pytest

TEST_DSN = os.environ.get(
    "RECALL_TEST_DATABASE_URL", "postgresql://recall@localhost:5432/recall_test"
)

# CI sets this. It is the load-bearing guard against recall's own cardinal sin:
# a hybrid search product whose CI quietly turns "Postgres is unreachable" into
# a wall of green skips. Locally, without it, a dev with no Postgres running
# still gets a clean skip so the fast suite stays usable.
REQUIRE_POSTGRES = os.environ.get("RECALL_REQUIRE_POSTGRES") == "1"


def _postgres_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(TEST_DSN, connect_timeout=3):
            return True
    except Exception as exc:
        if REQUIRE_POSTGRES:
            raise RuntimeError(
                "\n"
                "==============================================================\n"
                "RECALL_REQUIRE_POSTGRES=1 but Postgres is UNREACHABLE.\n"
                f"  DSN: {TEST_DSN}\n"
                f"  error: {exc!r}\n"
                "\n"
                "This is CI. An unreachable database must FAIL the run, never\n"
                "silently skip the integration tests — a green build that quietly\n"
                "skipped its own integration suite is exactly the kind of silent\n"
                "degradation recall exists to catch. Fix the Postgres service\n"
                "container or RECALL_TEST_DATABASE_URL; do not remove this guard.\n"
                "==============================================================\n"
            ) from exc
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_available(),
    reason=f"no Postgres at {TEST_DSN} (set RECALL_TEST_DATABASE_URL)",
)


def _pg_search_available() -> bool:
    """Whether the CONNECTED Postgres genuinely ships the pg_search extension.

    Checked against pg_available_extensions, which lists what the server COULD
    install, not just what has been CREATE EXTENSION'd already — that is what
    actually distinguishes a ParadeDB image (real BM25 possible) from a plain
    pgvector/pgvector image (pg_search genuinely absent, not just disabled).
    """
    if not _postgres_available():
        return False
    try:
        import psycopg

        with psycopg.connect(TEST_DSN, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_search')"
            )
            row = cur.fetchone()
            return bool(row[0]) if row else False
    except Exception:
        return False


requires_pg_search = pytest.mark.skipif(
    not _pg_search_available(),
    reason=(
        "pg_search extension is not available on this Postgres server — this is "
        "the genuine-fallback environment, not a simulated one, so real-BM25 "
        "tests correctly skip here while the ts_rank_cd fallback tests still run"
    ),
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

    def _make(
        dim: int = 8, model: str = "fake:fake", provider: str = "fake", *, pg_search_enabled=None
    ):
        store = PgVectorStore(TEST_DSN, pg_search_enabled=pg_search_enabled)
        store.drop_all()
        store.init(dim=dim, model=model, provider=provider)
        created.append(store)
        return store

    yield _make

    for store in created:
        store.drop_all()
