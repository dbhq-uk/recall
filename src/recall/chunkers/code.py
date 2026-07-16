from __future__ import annotations

from dataclasses import dataclass

from recall.chunkers import MAX_CHUNK_CHARS
from recall.chunkers.text import chunk_text
from recall.models import Chunk

# Node types that mean "a function" and "a class-like container", per grammar.
_FUNC_TYPES = {
    "function_definition",
    "function_declaration",
    "function_item",
    "method_definition",
    "method_declaration",
    "func_literal",
    "arrow_function",
    "function_signature_item",
}
_CLASS_TYPES = {
    "class_definition",
    "class_declaration",
    "impl_item",
    "struct_item",
    "interface_declaration",
    "trait_item",
    "type_declaration",
    "module",
}


@dataclass
class _Span:
    start: int  # 0-based, inclusive
    end: int  # 0-based, inclusive
    name: str | None


def _node_name(node) -> str | None:
    ident = node.child_by_field_name("name")
    if ident is None:
        # Rust `impl Foo` uses `type`, not `name`.
        ident = node.child_by_field_name("type")
    return ident.text.decode("utf-8", "replace") if ident is not None else None


def _find_definitions(node, depth: int = 0) -> list[_Span]:
    """Collect definition spans without double-emitting a class body.

    A class with methods yields a header span (class line -> first method) plus one
    span per method, qualified as ``Class.method``. A class with no methods yields
    itself. Naive tree-walking emits the class AND its methods, duplicating the body.
    """
    spans: list[_Span] = []

    for child in node.children:
        if child.type in _CLASS_TYPES:
            cls_name = _node_name(child)
            methods = [gc for gc in _descend_for_methods(child) if gc.type in _FUNC_TYPES]
            if not methods:
                spans.append(_Span(child.start_point[0], child.end_point[0], cls_name))
                continue

            first = min(m.start_point[0] for m in methods)
            if first > child.start_point[0]:
                spans.append(_Span(child.start_point[0], first - 1, cls_name))
            for m in methods:
                mname = _node_name(m)
                qualified = f"{cls_name}.{mname}" if cls_name and mname else (mname or cls_name)
                spans.append(_Span(m.start_point[0], m.end_point[0], qualified))

        elif child.type in _FUNC_TYPES:
            spans.append(_Span(child.start_point[0], child.end_point[0], _node_name(child)))

        else:
            spans.extend(_find_definitions(child, depth + 1))

    return spans


def _descend_for_methods(class_node) -> list:
    """Methods of a class, looking through the intervening `body`/`block` node."""
    out = []
    for child in class_node.children:
        if child.type in _FUNC_TYPES:
            out.append(child)
        elif child.type in ("block", "class_body", "declaration_list", "body"):
            out.extend(gc for gc in child.children if gc.type in _FUNC_TYPES)
    return out


def chunk_code(text: str, *, source: str, rel_path: str, file_sha: str, lang: str) -> list[Chunk]:
    try:
        from tree_sitter_language_pack import get_parser

        parser = get_parser(lang)
        tree = parser.parse(text.encode("utf-8"))
    except Exception:
        # Unsupported grammar, or the grammar pack is unavailable. Windows, honestly.
        return chunk_text(text, source=source, rel_path=rel_path, file_sha=file_sha, lang=lang)

    lines = text.splitlines()
    spans = sorted(_find_definitions(tree.root_node), key=lambda s: s.start)

    if not spans:
        return chunk_text(text, source=source, rel_path=rel_path, file_sha=file_sha, lang=lang)

    # Gap spans: code outside any definition (imports, constants) must not be lost.
    pieces: list[_Span] = []
    cursor = 0
    for span in spans:
        if span.start > cursor:
            pieces.append(_Span(cursor, span.start - 1, None))
        pieces.append(span)
        cursor = max(cursor, span.end + 1)
    if cursor < len(lines):
        pieces.append(_Span(cursor, len(lines) - 1, None))

    chunks: list[Chunk] = []
    for piece in pieces:
        body = "\n".join(lines[piece.start : piece.end + 1]).strip()
        if not body:
            continue
        # A gap chunk (no symbol) that is pure punctuation — a lone `}`, `);`,
        # a blank line — is not worth an embedding. But keep gaps with real
        # content (imports, module constants): those must not be lost.
        if piece.name is None and not any(ch.isalnum() for ch in body):
            continue

        for part in _window_if_oversized(body):
            chunks.append(
                Chunk(
                    source=source,
                    rel_path=rel_path,
                    chunk_idx=len(chunks),
                    content=part,
                    context=piece.name,
                    lang=lang,
                    file_sha=file_sha,
                )
            )
    return chunks


def _window_if_oversized(body: str) -> list[str]:
    if len(body) <= MAX_CHUNK_CHARS:
        return [body]
    lines = body.splitlines()
    out: list[str] = []
    step = max(1, 60 - 10)
    for start in range(0, len(lines), step):
        part = "\n".join(lines[start : start + 60]).strip()
        if part:
            out.append(part)
        if start + 60 >= len(lines):
            break
    return out
