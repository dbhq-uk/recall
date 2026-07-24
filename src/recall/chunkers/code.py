from __future__ import annotations

from dataclasses import dataclass

from recall.chunkers import CODE_OVERLAP_LINES, CODE_WINDOW_LINES, MAX_CHUNK_CHARS
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


class _CodeChunks(list):
    """A plain list of Chunk, plus a flag callers can opt into reading.

    Subclassing list rather than returning a tuple/dataclass keeps every
    existing `chunks = chunk_code(...)` call site working unchanged — they
    still get something that behaves exactly like a list. Callers that care
    about honesty (indexer.py) read `.fell_back`; callers that don't (most
    tests) never notice the difference.
    """

    fell_back: bool = False


def _no_grammar_errors() -> tuple[type[BaseException], ...]:
    """The exception types that genuinely mean "no grammar available here".

    Resolved once, at import time, and deliberately NOT by naming the pack's
    exception class inside chunk_code's own `except` tuple: if the import that
    binds that name is itself what failed, evaluating the tuple raises
    UnboundLocalError and the fallback never runs — breaking precisely the
    no-pack environment the fallback exists to serve.
    """
    try:
        from tree_sitter_language_pack import Error as GrammarPackError
    except ImportError:
        # No pack, so the pack's own exceptions cannot be raised. ImportError
        # (added by the caller below) is the only thing left to catch.
        return ()
    return (GrammarPackError,)


_NO_GRAMMAR_ERRORS: tuple[type[BaseException], ...] = (ImportError, *_no_grammar_errors())


def chunk_code(text: str, *, source: str, rel_path: str, file_sha: str, lang: str) -> list[Chunk]:
    try:
        from tree_sitter_language_pack import get_parser

        parser = get_parser(lang)
        tree = parser.parse(text.encode("utf-8"))
    except _NO_GRAMMAR_ERRORS:
        # ImportError: the tree_sitter_language_pack extra isn't installed at all.
        # GrammarPackError (LanguageNotFoundError, DownloadError, ConfigError, ...):
        # this specific grammar isn't available, per the pack's own exception
        # hierarchy. Both are genuinely expected "no grammar" conditions.
        #
        # A bare `except Exception` here previously also swallowed a real
        # tree-sitter crash on a SUPPORTED grammar — invisible corruption of
        # the chunking for that file, exactly the silent degradation this
        # product exists to prevent. Anything other than the two cases above
        # (a segfault-adjacent crash, a bug in our span-walking code, etc.)
        # must propagate so it surfaces as a loud failure, not quietly worse
        # chunking.
        result = _CodeChunks(
            chunk_text(text, source=source, rel_path=rel_path, file_sha=file_sha, lang=lang)
        )
        result.fell_back = True
        return result

    lines = text.splitlines()
    spans = sorted(_find_definitions(tree.root_node), key=lambda s: s.start)

    if not spans:
        # NOT a grammar fallback: the grammar parsed fine, it just found no
        # function/class definitions (a constants module, a config file, an
        # empty __init__.py). Line-window chunking is the *correct* choice
        # here, not a degraded one, so this must not be counted alongside the
        # genuine "no grammar available" case above.
        result = _CodeChunks(
            chunk_text(text, source=source, rel_path=rel_path, file_sha=file_sha, lang=lang)
        )
        result.fell_back = False
        return result

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

    chunks: list[Chunk] = _CodeChunks()
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
    step = max(1, CODE_WINDOW_LINES - CODE_OVERLAP_LINES)
    for start in range(0, len(lines), step):
        part = "\n".join(lines[start : start + CODE_WINDOW_LINES]).strip()
        if part:
            out.append(part)
        if start + CODE_WINDOW_LINES >= len(lines):
            break
    return out
