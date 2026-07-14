import pytest

from recall.config import Registry
from recall.indexer import index_source
from tests.conftest import requires_postgres
from tests.support.fake_embedder import FakeEmbedder

pytestmark = [pytest.mark.integration, requires_postgres]


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("RECALL_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "brain"
    (root / "notes").mkdir(parents=True)
    (root / ".recall.toml").write_text('[source]\ntag = "brain"\ninclude = ["**/*.md"]\n')
    (root / "notes" / "van.md").write_text(
        "# Van\n\n## Roof\n\n"
        + ("we fitted a pop-top so we can stand up inside. " * 12)
        + "\n\n## Engine\n\n"
        + ("the engine needed a full rebuild before the trip. " * 12)
    )
    (root / "notes" / "pg.md").write_text(
        "# Postgres\n\n" + ("full text search and ranking functions. " * 12)
    )
    Registry.load().register(root)
    return root


def test_index_writes_chunks(store_factory, source):
    store = store_factory(dim=8)
    report = index_source("brain", registry=Registry.load(), store=store, embedder=FakeEmbedder(dim=8))
    assert report.files_indexed == 2
    assert report.chunks_written > 0
    assert store.stats().sources == {"brain": report.chunks_written}


def test_reindexing_unchanged_files_SKIPS_them(store_factory, source):
    """file_sha is the whole change-detection story."""
    store = store_factory(dim=8)
    emb = FakeEmbedder(dim=8)
    index_source("brain", registry=Registry.load(), store=store, embedder=emb)
    second = index_source("brain", registry=Registry.load(), store=store, embedder=emb)
    assert second.files_skipped == 2
    assert second.files_indexed == 0


def test_a_changed_file_is_reindexed(store_factory, source):
    store = store_factory(dim=8)
    emb = FakeEmbedder(dim=8)
    index_source("brain", registry=Registry.load(), store=store, embedder=emb)
    (source / "notes" / "van.md").write_text("# Van\n\n" + ("completely new content here. " * 12))
    report = index_source("brain", registry=Registry.load(), store=store, embedder=emb)
    assert report.files_indexed == 1
    assert report.files_skipped == 1


def test_a_DELETED_file_has_its_chunks_pruned(store_factory, source):
    store = store_factory(dim=8)
    emb = FakeEmbedder(dim=8)
    index_source("brain", registry=Registry.load(), store=store, embedder=emb)
    (source / "notes" / "pg.md").unlink()
    report = index_source("brain", registry=Registry.load(), store=store, embedder=emb)
    assert report.files_pruned == 1
    with_pg = [p for p in store.file_shas("brain")]
    assert "notes/pg.md" not in with_pg


def test_a_shrunken_file_leaves_no_orphan_chunks(store_factory, source):
    store = store_factory(dim=8)
    emb = FakeEmbedder(dim=8)
    index_source("brain", registry=Registry.load(), store=store, embedder=emb)
    before = store.stats().total_chunks
    (source / "notes" / "van.md").write_text("# Van\n\ntiny now.\n")
    index_source("brain", registry=Registry.load(), store=store, embedder=emb)
    assert store.stats().total_chunks < before


def test_force_reindexes_everything(store_factory, source):
    store = store_factory(dim=8)
    emb = FakeEmbedder(dim=8)
    index_source("brain", registry=Registry.load(), store=store, embedder=emb)
    report = index_source("brain", registry=Registry.load(), store=store, embedder=emb, force=True)
    assert report.files_indexed == 2
    assert report.files_skipped == 0


def test_indexing_HARD_ERRORS_on_a_model_mismatch(store_factory, source):
    """Refuse to write a corrupt index."""
    from recall.errors import DimensionMismatchError

    store = store_factory(dim=8, model="fake:fake")
    with pytest.raises(DimensionMismatchError):
        index_source("brain", registry=Registry.load(), store=store, embedder=FakeEmbedder(dim=16))


def test_indexing_an_unknown_tag_lists_the_known_tags(store_factory, source):
    from recall.errors import UnknownTagError

    store = store_factory(dim=8)
    with pytest.raises(UnknownTagError, match="brain"):
        index_source("nope", registry=Registry.load(), store=store, embedder=FakeEmbedder(dim=8))


def test_the_embedded_text_carries_the_heading_trail(store_factory, source):
    """End-to-end proof that the trail survives all the way to the embedder."""
    seen: list[str] = []

    class Spy(FakeEmbedder):
        def embed_documents(self, texts):
            seen.extend(texts)
            return super().embed_documents(texts)

    store = store_factory(dim=8)
    index_source("brain", registry=Registry.load(), store=store, embedder=Spy(dim=8))
    assert any(t.startswith("Van > Roof\n\n") for t in seen)
