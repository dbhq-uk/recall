from __future__ import annotations

from recall.chunkers import CODE_OVERLAP_LINES, CODE_WINDOW_LINES
from recall.models import Chunk


def chunk_text(
    text: str,
    *,
    source: str,
    rel_path: str,
    file_sha: str,
    lang: str | None = None,
    window: int = CODE_WINDOW_LINES,
    overlap: int = CODE_OVERLAP_LINES,
) -> list[Chunk]:
    """Fixed line windows with overlap. The fallback for anything we cannot parse."""
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        return []

    chunks: list[Chunk] = []
    step = max(1, window - overlap)
    for start in range(0, len(lines), step):
        body = "\n".join(lines[start : start + window]).strip()
        if not body:
            continue
        chunks.append(
            Chunk(
                source=source,
                rel_path=rel_path,
                chunk_idx=len(chunks),
                content=body,
                context=None,
                lang=lang,
                file_sha=file_sha,
            )
        )
        if start + window >= len(lines):
            break
    return chunks
