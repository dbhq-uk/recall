from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

from recall.errors import ConfigError, UnknownTagError

DEFAULT_INCLUDE = ["**/*.md"]
DEFAULT_EXCLUDE = ["**/node_modules/**", "**/.git/**", "**/.venv/**", "**/__pycache__/**"]
MARKER = ".recall.toml"


def config_dir() -> Path:
    """Machine-local config. Overridable so tests never touch the real one."""
    if override := os.environ.get("RECALL_CONFIG_DIR"):
        return Path(override)
    return Path.home() / ".config" / "recall"


@dataclass(frozen=True)
class SourceConfig:
    """The in-source marker. Committed, so it travels with the source through git
    and is correct on every machine by construction."""

    tag: str
    include: list[str] = field(default_factory=lambda: list(DEFAULT_INCLUDE))
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))


def load_source_config(root: Path) -> SourceConfig:
    marker = root / MARKER
    if not marker.is_file():
        raise ConfigError(
            f"No {MARKER} found at {root}. A source declares its own tag in "
            f"{MARKER} so the tag travels with the source. Create one:\n\n"
            f'[source]\ntag = "my-tag"\ninclude = ["**/*.md"]\n'
        )
    try:
        data = tomllib.loads(marker.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{marker} is not valid TOML: {exc}") from exc

    section = data.get("source", {})
    tag = section.get("tag")
    if not tag:
        raise ConfigError(f"{marker} has no [source] tag. A source must declare a tag.")

    return SourceConfig(
        tag=tag,
        include=section.get("include", list(DEFAULT_INCLUDE)),
        exclude=section.get("exclude", list(DEFAULT_EXCLUDE)),
    )


def find_source_root(start: Path) -> Path | None:
    """Walk up looking for the in-source marker. Used by `recall serve` to resolve
    the current silo from the working directory."""
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / MARKER).is_file():
            return candidate
    return None


class Registry:
    """Maps tag -> local path on THIS machine.

    This is the only place a path lives. Nothing else in recall — and in
    particular nothing in the store — may know about absolute paths.
    """

    def __init__(self, paths: dict[str, Path]) -> None:
        self._paths = paths

    @classmethod
    def _file(cls) -> Path:
        return config_dir() / "registry.toml"

    @classmethod
    def load(cls) -> Registry:
        f = cls._file()
        if not f.is_file():
            return cls({})
        data = tomllib.loads(f.read_text())
        sources = data.get("sources", {})
        return cls({tag: Path(v["path"]) for tag, v in sources.items()})

    def save(self) -> None:
        f = self._file()
        f.parent.mkdir(parents=True, exist_ok=True)
        payload = {"sources": {tag: {"path": str(p)} for tag, p in sorted(self._paths.items())}}
        f.write_text(tomli_w.dumps(payload))

    def register(self, path: Path) -> str:
        """Read the source's own marker to learn its tag, then map tag -> this path."""
        path = path.resolve()
        tag = load_source_config(path).tag
        self._paths[tag] = path
        self.save()
        return tag

    def path_for(self, tag: str) -> Path:
        if tag not in self._paths:
            raise UnknownTagError(tag, self.tags())
        return self._paths[tag]

    def tags(self) -> list[str]:
        return sorted(self._paths)


@dataclass(frozen=True)
class RecallConfig:
    database_url: str = "postgresql:///recall"
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    embedding_endpoint: str = "http://localhost:11434"
    rrf_k: int = 60


def load_config() -> RecallConfig:
    """Config file, then env overrides. Env always wins."""
    f = config_dir() / "config.toml"
    data: dict = tomllib.loads(f.read_text()) if f.is_file() else {}
    db = data.get("database", {})
    emb = data.get("embedding", {})
    search = data.get("search", {})

    defaults = RecallConfig()
    return RecallConfig(
        database_url=os.environ.get("RECALL_DATABASE_URL", db.get("url", defaults.database_url)),
        embedding_provider=os.environ.get(
            "RECALL_EMBEDDING_PROVIDER", emb.get("provider", defaults.embedding_provider)
        ),
        embedding_model=os.environ.get(
            "RECALL_EMBEDDING_MODEL", emb.get("model", defaults.embedding_model)
        ),
        embedding_endpoint=os.environ.get(
            "RECALL_EMBEDDING_ENDPOINT", emb.get("endpoint", defaults.embedding_endpoint)
        ),
        rrf_k=int(os.environ.get("RECALL_RRF_K", search.get("rrf_k", defaults.rrf_k))),
    )
