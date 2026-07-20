from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from recall.config import Registry, find_source_root, load_config, load_source_config
from recall.embedders import build_embedder
from recall.errors import ConfigError, InvalidLimitError
from recall.store.pgvector import PgVectorStore

CURRENT_SOURCE: str | None = None

mcp = FastMCP("recall")

# Construction is cached across tool calls within one running server — a fresh
# PgVectorStore/embedder per call was pure waste, config does not change
# mid-process. Tests monkeypatch `_store` and `build_embedder` directly per
# test, which bypasses this cache entirely; reset_caches() exists so tests
# that DON'T monkeypatch (or that run before/after ones that do) never see a
# stale cached object leak across test boundaries.
_store_cache: PgVectorStore | None = None
_embedder_cache: Any = None


def reset_caches() -> None:
    """Clear the cached store/embedder. Call this from build_server() and from
    test fixtures — without it, a real object cached in one test could leak
    into the next, defeating that test's monkeypatch."""
    global _store_cache, _embedder_cache
    _store_cache = None
    _embedder_cache = None


def _store() -> PgVectorStore:
    global _store_cache
    if _store_cache is None:
        _store_cache = PgVectorStore(load_config().database_url)
    return _store_cache


def _get_embedder(config: Any) -> Any:
    global _embedder_cache
    if _embedder_cache is None:
        _embedder_cache = build_embedder(config)
    return _embedder_cache


def resolve_current_source(cwd: Path, explicit: str | None) -> str:
    """--source wins; otherwise walk up from the working directory for a marker."""
    if explicit:
        return explicit
    if root := find_source_root(cwd):
        return load_source_config(root).tag
    raise ConfigError(
        "Cannot tell which source this is. recall serve needs either --source <tag>, "
        "or a .recall.toml somewhere at or above the working directory."
    )


@mcp.tool()
def recall_search(query: str, sources: list[str] | None = None, limit: int = 10) -> dict[str, Any]:
    """Search indexed notes and code. Hybrid: BM25 + dense vectors, fused by RRF.

    `sources` defaults to the current source. Pass a list of tags to span silos,
    or ["*"] for everything.
    """
    # Validated here too, not just in the store: a caller of this tool should
    # get a clear RecallError naming the bad value, not an opaque error surfaced
    # from deep inside the SQL layer. The store validates independently because
    # it has its own callers (eval/harness.py) that don't go through this tool.
    if limit < 1 or limit > PgVectorStore.MAX_LIMIT:
        raise InvalidLimitError(limit, PgVectorStore.MAX_LIMIT)

    config = load_config()
    store = _store()
    embedder = _get_embedder(config)

    targets = sources if sources else ([CURRENT_SOURCE] if CURRENT_SOURCE else ["*"])
    result = store.search(
        qvec=embedder.embed_query(query),
        qtext=query,
        sources=targets,
        limit=limit,
        k=config.rrf_k,
        w_dense=config.fusion_weight_dense,
        w_lexical=config.fusion_weight_lexical,
    )

    return {
        "results": [
            {
                "chunk_id": h.chunk_id,
                "source": h.source,
                "rel_path": h.rel_path,
                "context": h.context,
                "content": h.content,
                "lang": h.lang,
                "score": round(h.score, 6),
                "dense_rank": h.dense_rank,
                "lexical_rank": h.lexical_rank,
            }
            for h in result.hits
        ],
        # Never let a degraded result look healthy. The agent must know what it holds.
        "retrieval": {
            "lexical_ranker": result.lexical_ranker,
            "hybrid": result.is_hybrid,
            "dense_hits": result.dense_hit_count,
            "lexical_hits": result.lexical_hit_count,
            "rrf_k": config.rrf_k,
            "weight_dense": config.fusion_weight_dense,
            "weight_lexical": config.fusion_weight_lexical,
            "searched_sources": targets,
            "notes": result.notes,
        },
    }


@mcp.tool()
def recall_sources() -> dict[str, Any]:
    """What is indexed: tag, chunk count, last indexed, and whether it is registered here."""
    stats = _store().stats()
    registry = Registry.load()

    out = []
    for tag, count in stats.sources.items():
        try:
            path = str(registry.path_for(tag))
        except Exception:
            path = None
        ts = stats.last_indexed.get(tag)
        out.append(
            {
                "tag": tag,
                "chunks": count,
                "last_indexed": ts.isoformat() if ts else None,
                "registered_path": path,
            }
        )

    return {"sources": out, "current_source": CURRENT_SOURCE}


@mcp.tool()
def recall_status() -> dict[str, Any]:
    """Health: which lexical ranker is live, which embedding model, dimension, backend.

    This exists so the agent knows what it is holding. A hybrid search that has
    quietly become a dense-only search is worse than useless — and a search
    against a month-old index is the same failure mode with a different cause,
    so we report staleness here too.
    """
    stats = _store().stats()

    warnings: list[str] = []
    if stats.lexical_ranker != "bm25":
        warnings.append(
            "Lexical ranking is ts_rank_cd, which is not BM25: no term-frequency "
            "saturation, no document-length normalisation. Install ParadeDB's "
            "pg_search extension and reindex for real BM25."
        )

    # Registry.load() reads one small local TOML file — it is not a filesystem
    # walk over any source tree. Do NOT "improve" this into counting dirty
    # files under each registered path: a status call must stay cheap and
    # I/O-free over the source trees themselves. We report the last-indexed
    # timestamp and let the caller judge staleness against it.
    registry = Registry.load()
    never_indexed = [tag for tag in registry.tags() if tag not in stats.sources]
    for tag in never_indexed:
        warnings.append(
            f"Source {tag!r} is registered but has never been indexed. Run: recall index"
        )

    return {
        "backend": stats.backend,
        "lexical_ranker": stats.lexical_ranker,
        "embedding_provider": stats.embedding_provider,
        "embedding_model": stats.embedding_model,
        "embedding_dim": stats.embedding_dim,
        "total_chunks": stats.total_chunks,
        "current_source": CURRENT_SOURCE,
        "last_indexed": {
            tag: ts.isoformat() if ts else None for tag, ts in stats.last_indexed.items()
        },
        "warnings": warnings,
    }


def build_server(source: str | None = None) -> FastMCP:
    global CURRENT_SOURCE
    reset_caches()  # a fresh server run must not inherit a previous run's store/embedder
    CURRENT_SOURCE = resolve_current_source(Path.cwd(), source)
    return mcp
