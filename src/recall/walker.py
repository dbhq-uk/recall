from __future__ import annotations

import fnmatch
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from recall.config import SourceConfig

_READ_CHUNK = 65536


@dataclass(frozen=True)
class WalkedFile:
    """A file on this machine, plus the identity the store will actually use.

    ``rel_path`` is what gets stored. ``abs_path`` exists only so we can read the
    bytes, and it stops here.
    """

    rel_path: str
    abs_path: Path
    file_sha: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(_READ_CHUNK):
            h.update(block)
    return h.hexdigest()


def _is_text(path: Path) -> bool:
    """Cheap binary sniff: a NUL byte in the first 8 KiB means it is not text."""
    try:
        head = path.open("rb").read(8192)
    except OSError:
        return False
    return b"\x00" not in head


def _matches(rel: PurePosixPath, patterns: list[str]) -> bool:
    """Glob-match ``rel`` against ``patterns``, 3.12-safe (no ``PurePath.full_match``).

    ``**/x`` must also match ``x`` at the root (zero directories deep), which
    plain ``fnmatch`` does not give us for free.
    """
    s = str(rel)
    for p in patterns:
        if fnmatch.fnmatch(s, p):
            return True
        if p.startswith("**/") and fnmatch.fnmatch(s, p[3:]):
            return True
    return False


def walk_source(root: Path, config: SourceConfig) -> Iterator[WalkedFile]:
    """Yield every file in the source that include/exclude admit, in sorted order.

    Sorted because a deterministic walk means deterministic chunk_idx values,
    which means re-indexing an unchanged file is genuinely a no-op.
    """
    root = root.resolve()
    for abs_path in sorted(root.rglob("*")):
        if not abs_path.is_file():
            continue
        rel = PurePosixPath(abs_path.relative_to(root).as_posix())
        if _matches(rel, config.exclude):
            continue
        if not _matches(rel, config.include):
            continue
        if not _is_text(abs_path):
            continue
        yield WalkedFile(
            rel_path=str(rel),
            abs_path=abs_path,
            file_sha=sha256_file(abs_path),
        )
