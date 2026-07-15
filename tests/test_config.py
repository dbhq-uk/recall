from pathlib import Path

import pytest

from recall.config import (
    Registry,
    config_dir,
    find_source_root,
    load_config,
    load_source_config,
)
from recall.errors import ConfigError, UnknownTagError


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never touch the real ~/.config/recall during tests."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setenv("RECALL_CONFIG_DIR", str(cfg))
    return cfg


def write_source(root: Path, tag: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".recall.toml").write_text(
        f'[source]\ntag = "{tag}"\n'
        'include = ["**/*.md"]\n'
        'exclude = ["**/node_modules/**", "**/.git/**"]\n'
    )
    return root


def test_config_dir_honours_env_override(isolated_config):
    assert config_dir() == isolated_config


def test_load_source_config_reads_the_in_source_marker(tmp_path):
    root = write_source(tmp_path / "brain", "brain")
    sc = load_source_config(root)
    assert sc.tag == "brain"
    assert sc.include == ["**/*.md"]
    assert "**/.git/**" in sc.exclude


def test_load_source_config_errors_when_marker_missing(tmp_path):
    with pytest.raises(ConfigError, match=".recall.toml"):
        load_source_config(tmp_path)


def test_load_source_config_errors_when_tag_missing(tmp_path):
    (tmp_path / ".recall.toml").write_text('[source]\ninclude = ["**/*.md"]\n')
    with pytest.raises(ConfigError, match="tag"):
        load_source_config(tmp_path)


def test_find_source_root_walks_up_from_a_nested_directory(tmp_path):
    root = write_source(tmp_path / "brain", "brain")
    nested = root / "areas" / "travel"
    nested.mkdir(parents=True)
    assert find_source_root(nested) == root


def test_find_source_root_returns_none_when_not_in_a_source(tmp_path):
    assert find_source_root(tmp_path) is None


def test_register_learns_the_tag_from_the_source(tmp_path):
    root = write_source(tmp_path / "brain", "brain")
    reg = Registry.load()
    tag = reg.register(root)
    assert tag == "brain"
    assert reg.path_for("brain") == root


def test_registry_persists_across_loads(tmp_path):
    root = write_source(tmp_path / "brain", "brain")
    Registry.load().register(root)
    assert Registry.load().path_for("brain") == root


def test_unknown_tag_error_lists_the_known_tags(tmp_path):
    Registry.load().register(write_source(tmp_path / "brain", "brain"))
    Registry.load().register(write_source(tmp_path / "dbhq", "dbhq"))
    with pytest.raises(UnknownTagError) as exc:
        Registry.load().path_for("nope")
    msg = str(exc.value)
    assert "brain" in msg and "dbhq" in msg


def test_PATH_INDEPENDENCE_INVARIANT_source_survives_moving_machines(tmp_path):
    """THE load-bearing invariant (design §Source identity).

    A path is a machine-local accident; a tag is the identity. Index a source at
    one path, move it, re-register it, and the tag must still resolve. Nothing
    about the source's identity may depend on where it happened to live.
    """
    old = write_source(tmp_path / "machine_a" / "brain", "brain")
    reg = Registry.load()
    reg.register(old)
    assert reg.path_for("brain") == old

    # The source moves: different machine, different path. Same tag, because the
    # tag travels inside the source in .recall.toml, committed to git.
    new = tmp_path / "machine_b" / "notes" / "brain"
    new.parent.mkdir(parents=True)
    old.rename(new)

    reg2 = Registry.load()
    reg2.register(new)
    assert reg2.path_for("brain") == new
    # And the tag we would write into the store is unchanged by the move.
    assert load_source_config(new).tag == "brain"


def test_registry_file_lives_where_the_design_says(isolated_config, tmp_path):
    Registry.load().register(write_source(tmp_path / "brain", "brain"))
    assert (isolated_config / "registry.toml").exists()


def test_load_config_has_the_designed_defaults(isolated_config):
    cfg = load_config()
    assert cfg.embedding_provider == "ollama"
    assert cfg.embedding_model == "nomic-embed-text"
    assert cfg.embedding_endpoint == "http://localhost:11434"
    assert cfg.rrf_k == 10
    assert cfg.fusion_weight_dense == pytest.approx(0.7)
    assert cfg.fusion_weight_lexical == pytest.approx(0.3)


def test_env_overrides_beat_the_config_file(isolated_config, monkeypatch):
    monkeypatch.setenv("RECALL_DATABASE_URL", "postgresql://x@y/z")
    assert load_config().database_url == "postgresql://x@y/z"


def test_malformed_config_toml_is_a_clean_error_not_a_traceback(isolated_config):
    (isolated_config / "config.toml").write_text("this is not valid toml [[[")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config()


def test_malformed_registry_toml_is_a_clean_error_not_a_traceback(isolated_config):
    (isolated_config / "registry.toml").write_text("also not valid toml [[[")
    with pytest.raises(ConfigError, match="not valid TOML"):
        Registry.load()


def test_a_non_integer_rrf_k_is_a_clean_error_not_a_traceback(isolated_config, monkeypatch):
    monkeypatch.setenv("RECALL_RRF_K", "not-a-number")
    with pytest.raises(ConfigError, match="rrf_k"):
        load_config()


def test_fusion_weight_env_overrides_beat_the_config_file(isolated_config, monkeypatch):
    monkeypatch.setenv("RECALL_FUSION_WEIGHT_DENSE", "0.7")
    monkeypatch.setenv("RECALL_FUSION_WEIGHT_LEXICAL", "0.3")
    cfg = load_config()
    assert cfg.fusion_weight_dense == pytest.approx(0.7)
    assert cfg.fusion_weight_lexical == pytest.approx(0.3)


def test_fusion_weights_come_from_the_search_section_of_the_config_file(isolated_config):
    (isolated_config / "config.toml").write_text(
        "[search]\nweight_dense = 0.6\nweight_lexical = 0.4\n"
    )
    cfg = load_config()
    assert cfg.fusion_weight_dense == pytest.approx(0.6)
    assert cfg.fusion_weight_lexical == pytest.approx(0.4)


def test_a_non_float_fusion_weight_dense_is_a_clean_error_not_a_traceback(
    isolated_config, monkeypatch
):
    monkeypatch.setenv("RECALL_FUSION_WEIGHT_DENSE", "not-a-number")
    with pytest.raises(ConfigError, match="fusion_weight_dense"):
        load_config()


def test_a_non_float_fusion_weight_lexical_is_a_clean_error_not_a_traceback(
    isolated_config, monkeypatch
):
    monkeypatch.setenv("RECALL_FUSION_WEIGHT_LEXICAL", "not-a-number")
    with pytest.raises(ConfigError, match="fusion_weight_lexical"):
        load_config()


def test_a_negative_fusion_weight_is_a_clean_error_not_a_traceback(isolated_config, monkeypatch):
    monkeypatch.setenv("RECALL_FUSION_WEIGHT_DENSE", "-0.1")
    with pytest.raises(ConfigError, match="fusion_weight_dense"):
        load_config()


def test_both_fusion_weights_zero_is_a_clean_error_not_a_traceback(isolated_config, monkeypatch):
    monkeypatch.setenv("RECALL_FUSION_WEIGHT_DENSE", "0")
    monkeypatch.setenv("RECALL_FUSION_WEIGHT_LEXICAL", "0")
    with pytest.raises(ConfigError, match="fusion_weight"):
        load_config()
