from pathlib import Path

from recall.config import SourceConfig
from recall.walker import sha256_file, walk_source


def build(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def test_walk_includes_matching_files(tmp_path):
    root = build(tmp_path, {"a.md": "one", "notes/b.md": "two"})
    cfg = SourceConfig(tag="t", include=["**/*.md"], exclude=[])
    rels = sorted(f.rel_path for f in walk_source(root, cfg))
    assert rels == ["a.md", "notes/b.md"]


def test_walk_excludes_non_matching_extensions(tmp_path):
    root = build(tmp_path, {"a.md": "one", "b.txt": "two"})
    cfg = SourceConfig(tag="t", include=["**/*.md"], exclude=[])
    assert [f.rel_path for f in walk_source(root, cfg)] == ["a.md"]


def test_exclude_beats_include(tmp_path):
    root = build(tmp_path, {"a.md": "one", "node_modules/dep/b.md": "two"})
    cfg = SourceConfig(tag="t", include=["**/*.md"], exclude=["**/node_modules/**"])
    assert [f.rel_path for f in walk_source(root, cfg)] == ["a.md"]


def test_rel_paths_use_forward_slashes_and_are_never_absolute(tmp_path):
    """The store must never see an absolute path. Ever."""
    root = build(tmp_path, {"deep/nested/dir/file.md": "x"})
    cfg = SourceConfig(tag="t", include=["**/*.md"], exclude=[])
    f = next(iter(walk_source(root, cfg)))
    assert f.rel_path == "deep/nested/dir/file.md"
    assert not Path(f.rel_path).is_absolute()
    assert str(tmp_path) not in f.rel_path


def test_sha_changes_when_content_changes(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("one")
    first = sha256_file(p)
    p.write_text("two")
    assert sha256_file(p) != first


def test_sha_is_stable_for_identical_content(tmp_path):
    (tmp_path / "a.md").write_text("same")
    (tmp_path / "b.md").write_text("same")
    assert sha256_file(tmp_path / "a.md") == sha256_file(tmp_path / "b.md")


def test_walked_file_carries_its_sha(tmp_path):
    root = build(tmp_path, {"a.md": "hello"})
    cfg = SourceConfig(tag="t", include=["**/*.md"], exclude=[])
    f = next(iter(walk_source(root, cfg)))
    assert f.file_sha == sha256_file(root / "a.md")


def test_walk_skips_binary_and_unreadable_files(tmp_path):
    root = build(tmp_path, {"a.md": "text"})
    (root / "b.md").write_bytes(b"\x00\x01\x02\xff\xfe")
    cfg = SourceConfig(tag="t", include=["**/*.md"], exclude=[])
    assert [f.rel_path for f in walk_source(root, cfg)] == ["a.md"]


def test_walk_is_deterministic(tmp_path):
    root = build(tmp_path, {"c.md": "3", "a.md": "1", "b.md": "2"})
    cfg = SourceConfig(tag="t", include=["**/*.md"], exclude=[])
    first = [f.rel_path for f in walk_source(root, cfg)]
    second = [f.rel_path for f in walk_source(root, cfg)]
    assert first == second == sorted(first)
