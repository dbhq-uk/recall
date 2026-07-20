from __future__ import annotations

from dataclasses import dataclass

from recall.chunkers import chunk_file
from recall.config import Registry, load_source_config
from recall.embedders import Embedder
from recall.models import Chunk
from recall.store.pgvector import PgVectorStore
from recall.walker import walk_source

EMBED_BATCH = 64


@dataclass(frozen=True)
class IndexReport:
    tag: str
    files_seen: int
    files_indexed: int
    files_skipped: int
    files_pruned: int
    chunks_written: int
    # Files where tree-sitter chunking degraded to line-window chunking because
    # no grammar was available (missing pack, unsupported language). Distinct
    # from "no definitions found" (a legitimately correct line-window choice,
    # not a degradation) — see chunk_code's own comment for the split. Every
    # degradation must be reported in-band, per the project's honesty rule.
    files_fallback_chunked: int = 0


def index_source(
    tag: str,
    *,
    registry: Registry,
    store: PgVectorStore,
    embedder: Embedder,
    force: bool = False,
) -> IndexReport:
    """Walk the source, hash each file, skip files whose file_sha is unchanged,
    upsert the rest, delete chunks whose files have disappeared.

    That is the entire freshness strategy. A rebuild at realistic sizes takes
    seconds, and a rebuild is always correct.
    """
    root = registry.path_for(tag)  # raises UnknownTagError, listing the known tags
    config = load_source_config(root)

    # Refuse to write a corrupt index. This must happen before any embedding work.
    store.check_model(embedder.name, embedder.dim)

    known = {} if force else store.file_shas(tag)

    seen: set[str] = set()
    indexed = skipped = chunks_written = fallback_chunked = 0
    pending: list[Chunk] = []

    def flush() -> int:
        nonlocal pending
        if not pending:
            return 0
        vectors = embedder.embed_documents([c.embed_text for c in pending])
        store.upsert(
            [
                Chunk(
                    source=c.source,
                    rel_path=c.rel_path,
                    chunk_idx=c.chunk_idx,
                    content=c.content,
                    context=c.context,
                    lang=c.lang,
                    file_sha=c.file_sha,
                    embedding=v,
                )
                for c, v in zip(pending, vectors, strict=True)
            ]
        )
        written = len(pending)
        pending = []
        return written

    for walked in walk_source(root, config):
        seen.add(walked.rel_path)

        if known.get(walked.rel_path) == walked.file_sha:
            skipped += 1
            continue

        # The file changed. Drop its old chunks first, or a file that shrank from
        # 5 chunks to 2 leaves 3 stale ones behind.
        store.delete_file(tag, walked.rel_path)

        text = walked.abs_path.read_text(encoding="utf-8", errors="replace")
        file_chunks = chunk_file(
            text, source=tag, rel_path=walked.rel_path, file_sha=walked.file_sha
        )
        indexed += 1
        if getattr(file_chunks, "fell_back", False):
            fallback_chunked += 1

        for chunk in file_chunks:
            pending.append(chunk)
            if len(pending) >= EMBED_BATCH:
                chunks_written += flush()

    chunks_written += flush()
    store.prune(tag, seen)

    # Report files pruned, not chunks — that is what the user deleted.
    pruned_files = len(set(known) - seen) if known else 0

    return IndexReport(
        tag=tag,
        files_seen=len(seen),
        files_indexed=indexed,
        files_skipped=skipped,
        files_pruned=pruned_files,
        chunks_written=chunks_written,
        files_fallback_chunked=fallback_chunked,
    )
