"""The product's central promise, under test.

recall never degrades silently. If the real BM25 ranker is missing, or the lexical
half of a query returns nothing, recall says so. A hybrid search that has quietly
become a dense-only search is worse than useless, because it looks like it is
working.

This file is deliberately self-contained and greppable: every assertion here maps
directly onto a sentence in CLAUDE.md's "Honest failure" section. Where a test
would exactly duplicate the mechanics already covered in test_store_search.py, we
instead assert the PROMISE — that the fallback is real, announced, still usable,
and never dressed up as something it is not — against a real Postgres, not a mock.
"""

import psycopg
import pytest

from recall.models import Chunk
from tests.conftest import TEST_DSN, requires_pg_search, requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]

DIM = 8


def vec(*first: float) -> list[float]:
    v = [0.0] * DIM
    for i, x in enumerate(first):
        v[i] = float(x)
    return v


def load(store):
    store.upsert(
        [
            Chunk(
                source="s",
                rel_path="van.md",
                chunk_idx=0,
                content="the van has a pop-top roof for sleeping",
                context=None,
                lang="markdown",
                file_sha="x",
                embedding=vec(1, 0, 0),
            ),
            Chunk(
                source="s",
                rel_path="pg.md",
                chunk_idx=0,
                content="postgres full text search and ranking",
                context=None,
                lang="markdown",
                file_sha="x",
                embedding=vec(0, 1, 0),
            ),
        ]
    )
    return store


@requires_pg_search
def test_pg_search_is_actually_installed_on_this_machine() -> None:
    """If this fails, the BM25 half of this file is not testing what it claims."""
    with psycopg.connect(TEST_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='pg_search')")
        row = cur.fetchone()
        assert row is not None and row[0], "pg_search absent — the BM25 path is NOT being tested"


@requires_pg_search
def test_with_pg_search_the_ranker_is_bm25_and_nothing_is_warned(store_factory) -> None:
    store = load(store_factory(dim=DIM, pg_search_enabled=True))
    r = store.search(qvec=vec(1, 0, 0), qtext="pop-top roof", sources=["s"], limit=10, k=60)
    assert r.lexical_ranker == "bm25"
    assert r.is_hybrid
    assert r.notes == []


def test_without_pg_search_the_ranker_is_ts_rank_cd_AND_IT_SAYS_SO(store_factory) -> None:
    store = load(store_factory(dim=DIM, pg_search_enabled=False))
    r = store.search(qvec=vec(1, 0, 0), qtext="pop-top roof", sources=["s"], limit=10, k=60)
    assert r.lexical_ranker == "ts_rank_cd"
    assert r.notes, "the fallback must be announced, never hidden"
    assert any("not BM25" in n for n in r.notes)


@requires_pg_search
def test_BOTH_PATHS_STILL_RETURN_USABLE_RESULTS(store_factory) -> None:
    """The fallback is honest, not broken. ts_rank_cd is a real ranker."""
    for enabled in (True, False):
        store = load(store_factory(dim=DIM, pg_search_enabled=enabled))
        r = store.search(qvec=vec(1, 0, 0), qtext="pop-top roof", sources=["s"], limit=10, k=60)
        assert r.hits[0].rel_path == "van.md"


def test_the_two_paths_use_genuinely_different_sql() -> None:
    """Guards against the two query constants silently drifting into one — the
    exact failure mode that would make the honesty promise a lie without any
    test noticing, because the ranker LABEL would still say the right thing
    while the SQL underneath quietly ran BM25 (or vice versa) regardless."""
    from recall.store import sql

    assert "paradedb.match" in sql.SEARCH_BM25
    assert "ts_rank_cd" not in sql.SEARCH_BM25
    assert "ts_rank_cd" in sql.SEARCH_TS_RANK_CD
    assert "paradedb" not in sql.SEARCH_TS_RANK_CD


@requires_pg_search
def test_a_dense_only_result_is_never_dressed_up_as_hybrid(store_factory) -> None:
    """Under EITHER ranker: zero lexical hits must never be silently reported as
    a hybrid ranking. We still return the dense hits — we just refuse to
    mislabel them as fused."""
    for enabled in (True, False):
        store = load(store_factory(dim=DIM, pg_search_enabled=enabled))
        r = store.search(qvec=vec(1, 0, 0), qtext="zzzznotaword", sources=["s"], limit=10, k=60)
        assert r.lexical_hit_count == 0
        assert r.is_hybrid is False
        assert any("dense-only" in n for n in r.notes)
        assert r.hits, "we still return dense results — we just refuse to mislabel them"
