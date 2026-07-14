import psycopg
import pytest

from recall.models import Chunk
from tests.conftest import TEST_DSN, requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]


def mk(source="brain", rel_path="a.md", idx=0, content="body", sha="sha1", dim=8) -> Chunk:
    return Chunk(
        source=source,
        rel_path=rel_path,
        chunk_idx=idx,
        content=content,
        context="Trail",
        lang="markdown",
        file_sha=sha,
        embedding=[0.1] * dim,
    )


def test_upsert_inserts_chunks(store_factory):
    store = store_factory()
    store.upsert([mk(idx=0), mk(idx=1)])
    assert store.stats().total_chunks == 2


def test_upsert_is_idempotent_on_the_same_identity(store_factory):
    """Identity is (source, rel_path, chunk_idx). Re-indexing must not duplicate."""
    store = store_factory()
    store.upsert([mk(content="v1")])
    store.upsert([mk(content="v2")])
    assert store.stats().total_chunks == 1
    with psycopg.connect(TEST_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT content FROM chunks")
        assert cur.fetchone()[0] == "v2"


def test_NO_ABSOLUTE_PATH_IS_EVER_WRITTEN_TO_THE_STORE(store_factory):
    """The load-bearing invariant, enforced at the storage boundary."""
    store = store_factory()
    store.upsert([mk(rel_path="notes/van.md")])
    with psycopg.connect(TEST_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT rel_path FROM chunks")
        stored = cur.fetchone()[0]
    assert stored == "notes/van.md"
    assert not stored.startswith("/")
    assert "home" not in stored


def test_delete_source_removes_only_that_silo(store_factory):
    store = store_factory()
    store.upsert([mk(source="brain"), mk(source="dbhq")])
    store.delete_source("brain")
    assert store.stats().sources == {"dbhq": 1}


def test_prune_removes_chunks_whose_files_have_disappeared(store_factory):
    store = store_factory()
    store.upsert([mk(rel_path="kept.md"), mk(rel_path="deleted.md")])
    removed = store.prune("brain", seen={"kept.md"})
    assert removed == 1
    assert store.stats().total_chunks == 1


def test_prune_never_touches_another_source(store_factory):
    store = store_factory()
    store.upsert([mk(source="brain", rel_path="a.md"), mk(source="dbhq", rel_path="b.md")])
    store.prune("brain", seen=set())
    assert store.stats().sources == {"dbhq": 1}


def test_file_shas_reports_what_is_indexed(store_factory):
    store = store_factory()
    store.upsert([mk(rel_path="a.md", sha="sha_a"), mk(rel_path="b.md", sha="sha_b")])
    assert store.file_shas("brain") == {"a.md": "sha_a", "b.md": "sha_b"}


def test_delete_file_removes_all_chunks_of_that_file(store_factory):
    store = store_factory()
    store.upsert([mk(rel_path="a.md", idx=0), mk(rel_path="a.md", idx=1), mk(rel_path="b.md")])
    store.delete_file("brain", "a.md")
    assert store.stats().total_chunks == 1


def test_reindexing_a_shrunken_file_drops_its_orphan_chunks(store_factory):
    """A file that had 3 chunks and now has 1 must not leave 2 stale chunks behind."""
    store = store_factory()
    store.upsert([mk(idx=0), mk(idx=1), mk(idx=2)])
    store.delete_file("brain", "a.md")
    store.upsert([mk(idx=0, content="shrunk")])
    assert store.stats().total_chunks == 1


def test_stats_reports_the_model_and_the_ranker(store_factory):
    store = store_factory(dim=8, model="fake:fake", provider="fake")
    store.upsert([mk()])
    s = store.stats()
    assert s.embedding_model == "fake:fake"
    assert s.embedding_dim == 8
    assert s.backend == "pgvector"
    assert s.lexical_ranker in ("bm25", "ts_rank_cd")


def test_upsert_of_an_empty_list_is_a_no_op(store_factory):
    store = store_factory()
    store.upsert([])
    assert store.stats().total_chunks == 0
