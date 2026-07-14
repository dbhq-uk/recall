import pytest
from typer.testing import CliRunner

from recall.cli import app
from tests.conftest import TEST_DSN, requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]
runner = CliRunner()


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RECALL_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("RECALL_DATABASE_URL", TEST_DSN)
    monkeypatch.setenv("RECALL_EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("RECALL_EMBEDDING_MODEL", "fake")


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    """Keep the CLI tests off the network. Retrieval quality is the harness's job."""
    from tests.support.fake_embedder import FakeEmbedder
    monkeypatch.setattr("recall.cli.build_embedder", lambda cfg: FakeEmbedder(dim=8))


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "brain"
    root.mkdir()
    (root / ".recall.toml").write_text('[source]\ntag = "brain"\ninclude = ["**/*.md"]\n')
    (root / "a.md").write_text("# Van\n\n" + ("pop-top roof prose here. " * 15))
    return root


def test_init_creates_the_schema():
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "initialised" in result.stdout.lower()


def test_register_learns_the_tag_from_the_source(source):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["register", str(source)])
    assert result.exit_code == 0
    assert "brain" in result.stdout


def test_register_refuses_a_directory_with_no_marker(tmp_path):
    result = runner.invoke(app, ["register", str(tmp_path)])
    assert result.exit_code != 0
    assert ".recall.toml" in result.stdout


def test_index_reports_what_it_did(source):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["register", str(source)])
    result = runner.invoke(app, ["index", "brain"])
    assert result.exit_code == 0
    assert "brain" in result.stdout


def test_index_of_an_unknown_tag_lists_the_known_tags(source):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["register", str(source)])
    result = runner.invoke(app, ["index", "nope"])
    assert result.exit_code != 0
    assert "brain" in result.stdout  # tells you what you COULD have typed


def test_sources_lists_what_is_indexed(source):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["register", str(source)])
    runner.invoke(app, ["index", "brain"])
    result = runner.invoke(app, ["sources"])
    assert "brain" in result.stdout


def test_reindex_rebuilds_from_scratch(source):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["register", str(source)])
    runner.invoke(app, ["index", "brain"])
    result = runner.invoke(app, ["reindex", "brain"])
    assert result.exit_code == 0


def test_DOCTOR_REPORTS_WHICH_RANKER_IS_LIVE(source):
    """The honesty surface. It must never be coy about this."""
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    out = result.stdout.lower()
    assert "bm25" in out or "ts_rank_cd" in out
    assert "postgres" in out
    assert "embedding" in out


def test_doctor_reports_the_database_and_the_model():
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["doctor"])
    assert "fake" in result.stdout  # the configured embedding model


def test_a_bad_embedding_provider_is_a_clean_error_not_a_traceback(monkeypatch):
    # The autouse fake_embedder fixture replaces recall.cli.build_embedder with a
    # stub that ignores the configured provider entirely (that is what keeps the
    # rest of this suite off the network). Put the real one back for this test —
    # otherwise there is nothing here to raise ConfigError in the first place.
    from recall.embedders import build_embedder as real_build_embedder

    monkeypatch.setattr("recall.cli.build_embedder", real_build_embedder)
    monkeypatch.setenv("RECALL_EMBEDDING_PROVIDER", "bogus")
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 1
    assert "bogus" in result.stdout
    assert "Traceback" not in result.stdout


def test_a_bad_rrf_k_is_a_clean_error_not_a_traceback(monkeypatch):
    monkeypatch.setenv("RECALL_RRF_K", "not-a-number")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "rrf_k" in result.stdout
    assert "Traceback" not in result.stdout
