from __future__ import annotations

import math
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
        try:
            data = tomllib.loads(f.read_text())
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{f} is not valid TOML: {exc}") from exc
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
    rrf_k: int = 10
    # Convex-combination fusion weights (see store/sql.py for the formula).
    # Equal-weight RRF, measured against the golden set, loses to dense-only
    # retrieval on this corpus (see eval/harness.py). The IR literature
    # (Elastic's weighted-RRF write-up; alpha typically 0.3-0.7) supports a
    # moderate dense lean for prose/conceptual queries, so that is the
    # default here — a generalisation of RRF, not a fixture-specific tune.
    # It will not necessarily beat every half on every corpus; run the
    # harness and read the actual numbers rather than trusting this comment.
    fusion_weight_dense: float = 0.7
    fusion_weight_lexical: float = 0.3
    # CPU-only boxes are slow; a batch of large chunks can take minutes to embed.
    # A timeout that fires on a healthy-but-slow machine is a false honest-failure.
    embedding_timeout: float = 300.0


def load_config() -> RecallConfig:
    """Config file, then env overrides. Env always wins."""
    f = config_dir() / "config.toml"
    data: dict = {}
    if f.is_file():
        try:
            data = tomllib.loads(f.read_text())
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{f} is not valid TOML: {exc}") from exc
    db = data.get("database", {})
    emb = data.get("embedding", {})
    search = data.get("search", {})

    defaults = RecallConfig()
    raw_k = os.environ.get("RECALL_RRF_K", search.get("rrf_k", defaults.rrf_k))
    try:
        rrf_k = int(raw_k)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"rrf_k must be an integer, got {raw_k!r}") from exc

    raw_w_dense = os.environ.get(
        "RECALL_FUSION_WEIGHT_DENSE", search.get("weight_dense", defaults.fusion_weight_dense)
    )
    try:
        fusion_weight_dense = float(raw_w_dense)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"fusion_weight_dense must be a number, got {raw_w_dense!r}") from exc

    raw_w_lexical = os.environ.get(
        "RECALL_FUSION_WEIGHT_LEXICAL",
        search.get("weight_lexical", defaults.fusion_weight_lexical),
    )
    try:
        fusion_weight_lexical = float(raw_w_lexical)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"fusion_weight_lexical must be a number, got {raw_w_lexical!r}") from exc

    if not math.isfinite(fusion_weight_dense) or not math.isfinite(fusion_weight_lexical):
        raise ConfigError(
            "fusion_weight_dense and fusion_weight_lexical must be finite numbers, got "
            f"dense={fusion_weight_dense!r} lexical={fusion_weight_lexical!r}"
        )
    if fusion_weight_dense < 0 or fusion_weight_lexical < 0:
        raise ConfigError(
            "fusion_weight_dense and fusion_weight_lexical must be >= 0, got "
            f"dense={fusion_weight_dense!r} lexical={fusion_weight_lexical!r}"
        )
    if fusion_weight_dense == 0 and fusion_weight_lexical == 0:
        raise ConfigError(
            "fusion_weight_dense and fusion_weight_lexical cannot both be zero "
            "(a zero/zero weighting returns nothing meaningful)"
        )

    raw_timeout = os.environ.get(
        "RECALL_EMBEDDING_TIMEOUT", emb.get("timeout", defaults.embedding_timeout)
    )
    try:
        embedding_timeout = float(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"embedding_timeout must be a number, got {raw_timeout!r}") from exc

    if not math.isfinite(embedding_timeout) or embedding_timeout <= 0:
        raise ConfigError(
            f"embedding_timeout must be a finite number > 0, got {embedding_timeout!r}"
        )

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
        rrf_k=rrf_k,
        fusion_weight_dense=fusion_weight_dense,
        fusion_weight_lexical=fusion_weight_lexical,
        embedding_timeout=embedding_timeout,
    )
