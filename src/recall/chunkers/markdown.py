from __future__ import annotations

import re
from dataclasses import dataclass

from recall.chunkers import MAX_CHUNK_CHARS, MIN_CHUNK_CHARS, OVERLAP_CHARS
from recall.models import Chunk

_ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_FRONT_MATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)


@dataclass
class _Section:
    trail: list[str]
    lines: list[str]

    @property
    def context(self) -> str | None:
        return " > ".join(self.trail) if self.trail else None

    @property
    def body(self) -> str:
        return "\n".join(self.lines).strip()


def _strip_front_matter(text: str) -> str:
    return _FRONT_MATTER.sub("", text, count=1)


def _split_sections(text: str) -> list[_Section]:
    """Walk the document, tracking the heading stack and skipping fenced code.

    A heading inside a ``` or ~~~ fence is not a heading. This is the single
    easiest thing to get wrong here, and it silently shreds any document that
    contains a shell snippet.
    """
    sections: list[_Section] = []
    trail: list[str] = []
    current = _Section(trail=[], lines=[])
    fence: str | None = None

    for line in text.splitlines():
        if fence is not None:
            current.lines.append(line)
            if line.strip().startswith(fence):
                fence = None
            continue

        if m := _FENCE.match(line):
            fence = m.group(1)[0] * 3
            current.lines.append(line)
            continue

        if m := _ATX.match(line):
            if current.body:
                sections.append(current)
            level, title = len(m.group(1)), m.group(2)
            trail = trail[: level - 1]
            trail.append(title)
            current = _Section(trail=list(trail), lines=[])
            continue

        current.lines.append(line)

    if current.body:
        sections.append(current)
    return sections


def _merge_short_forward(sections: list[_Section]) -> list[_Section]:
    """A section under the floor merges into the next one, keeping the next
    section's trail (which is the more specific of the two)."""
    out: list[_Section] = []
    carry: _Section | None = None

    for sec in sections:
        if carry is not None:
            sec = _Section(trail=sec.trail, lines=[*carry.lines, "", *sec.lines])
            carry = None
        if len(sec.body) < MIN_CHUNK_CHARS:
            carry = sec
            continue
        out.append(sec)

    if carry is not None:
        if out:
            last = out[-1]
            out[-1] = _Section(trail=last.trail, lines=[*last.lines, "", *carry.lines])
        else:
            out.append(carry)  # whole document is short; keep it rather than lose it
    return out


def _split_long(body: str) -> list[str]:
    """Split on paragraph boundaries, with OVERLAP_CHARS of tail carried forward."""
    if len(body) <= MAX_CHUNK_CHARS:
        return [body]

    paras = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
    parts: list[str] = []
    buf = ""

    for para in paras:
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) > MAX_CHUNK_CHARS and buf:
            parts.append(buf)
            tail = buf[-OVERLAP_CHARS:]
            buf = f"{tail}\n\n{para}"
        else:
            buf = candidate

    if buf:
        parts.append(buf)

    # A single paragraph can still exceed the ceiling; hard-split it.
    final: list[str] = []
    for part in parts:
        while len(part) > MAX_CHUNK_CHARS:
            final.append(part[:MAX_CHUNK_CHARS])
            part = part[MAX_CHUNK_CHARS - OVERLAP_CHARS :]
        final.append(part)
    return final


def chunk_markdown(text: str, *, source: str, rel_path: str, file_sha: str) -> list[Chunk]:
    sections = _merge_short_forward(_split_sections(_strip_front_matter(text)))

    chunks: list[Chunk] = []
    for sec in sections:
        for body in _split_long(sec.body):
            if not body.strip():
                continue
            chunks.append(
                Chunk(
                    source=source,
                    rel_path=rel_path,
                    chunk_idx=len(chunks),
                    content=body,
                    context=sec.context,
                    lang="markdown",
                    file_sha=file_sha,
                )
            )
    return chunks
