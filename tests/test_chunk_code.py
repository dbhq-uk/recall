from recall.chunkers import chunk_file
from recall.chunkers.code import chunk_code
from recall.chunkers.text import chunk_text

KW = dict(source="repo", rel_path="src/app.py", file_sha="sha1")


def test_top_level_function_becomes_its_own_chunk():
    src = "def top_level(x):\n    return x + 1\n"
    chunks = chunk_code(src, lang="python", **KW)
    fn = [c for c in chunks if c.context == "top_level"][0]
    assert "return x + 1" in fn.content


def test_methods_are_chunked_with_a_qualified_symbol_name():
    src = """class Greeter:
    def hello(self, name):
        return f"hi {name}"

    def goodbye(self, name):
        return f"bye {name}"
"""
    contexts = {c.context for c in chunk_code(src, lang="python", **KW)}
    assert "Greeter.hello" in contexts
    assert "Greeter.goodbye" in contexts


def test_class_body_is_not_emitted_twice():
    """Naive tree-walking emits the whole class AND each method, duplicating the body."""
    src = """class Greeter:
    def hello(self):
        return "unique_marker_string"
"""
    chunks = chunk_code(src, lang="python", **KW)
    hits = [c for c in chunks if "unique_marker_string" in c.content]
    assert len(hits) == 1


def test_symbol_name_is_embedded_not_merely_stored():
    src = "def calculate_vat(amount):\n    return amount * 0.2\n"
    fn = [c for c in chunk_code(src, lang="python", **KW) if c.context == "calculate_vat"][0]
    assert fn.embed_text.startswith("calculate_vat\n\n")


def test_imports_and_module_level_code_are_not_lost():
    src = "import os\nimport sys\n\nCONSTANT = 42\n\ndef f():\n    return 1\n"
    chunks = chunk_code(src, lang="python", **KW)
    assert any("import os" in c.content for c in chunks)
    assert any("CONSTANT = 42" in c.content for c in chunks)


def test_stray_closing_brace_is_not_its_own_chunk_but_short_imports_survive():
    """A gap that is pure punctuation (a lone `}` after the last method) must not
    become a chunk. But a short real gap (imports, constants) must be kept — this
    is the exact tradeoff a naive length filter got wrong."""
    src = """import os from "os";

class Widget {
    build() {
        return 1;
    }
}
"""
    chunks = chunk_code(src, lang="typescript", source="r", rel_path="a.ts", file_sha="s")
    # No chunk is a bare brace / punctuation-only.
    assert not any(set(c.content.strip()) <= set("}{;) \n\t") for c in chunks if c.content.strip())
    # The import survived.
    assert any("import os" in c.content for c in chunks)


def test_typescript_functions_are_found():
    src = "export function greet(name: string): string {\n  return `hi ${name}`;\n}\n"
    chunks = chunk_code(src, lang="typescript", source="r", rel_path="a.ts", file_sha="s")
    assert any(c.context == "greet" for c in chunks)


def test_go_functions_are_found():
    src = "package main\n\nfunc Add(a int, b int) int {\n\treturn a + b\n}\n"
    chunks = chunk_code(src, lang="go", source="r", rel_path="a.go", file_sha="s")
    assert any(c.context == "Add" for c in chunks)


def test_rust_functions_are_found():
    src = "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n"
    chunks = chunk_code(src, lang="rust", source="r", rel_path="a.rs", file_sha="s")
    assert any(c.context == "add" for c in chunks)


def test_unsupported_language_falls_back_to_line_windows():
    """Design: 60-line windows with 10-line overlap."""
    src = "\n".join(f"line {i}" for i in range(140))
    chunks = chunk_text(src, source="r", rel_path="a.cobol", file_sha="s", lang="cobol")
    assert len(chunks) >= 2
    # 10-line overlap: the tail of chunk 0 reappears in chunk 1.
    assert "line 55" in chunks[0].content
    assert "line 55" in chunks[1].content


def test_line_window_chunks_are_sequential():
    src = "\n".join(f"line {i}" for i in range(200))
    chunks = chunk_text(src, source="r", rel_path="a.txt", file_sha="s")
    assert [c.chunk_idx for c in chunks] == list(range(len(chunks)))


def test_syntactically_broken_code_falls_back_rather_than_crashing():
    """A half-written file must not take the indexer down."""
    src = "def broken(:\n    this is not python at all ((( \n"
    chunks = chunk_code(src, lang="python", **KW)
    assert len(chunks) >= 1
    assert any("broken" in c.content for c in chunks)


def test_dispatch_routes_markdown_to_the_markdown_chunker():
    chunks = chunk_file("# Head\n\n" + ("prose. " * 60), source="s", rel_path="a.md", file_sha="x")
    assert chunks[0].lang == "markdown"
    assert chunks[0].context == "Head"


def test_dispatch_routes_python_to_the_code_chunker():
    chunks = chunk_file("def f():\n    return 1\n", source="s", rel_path="a.py", file_sha="x")
    assert chunks[0].lang == "python"
    assert any(c.context == "f" for c in chunks)


def test_dispatch_routes_unknown_extensions_to_line_windows():
    chunks = chunk_file("plain text here\n" * 100, source="s", rel_path="a.log", file_sha="x")
    assert len(chunks) >= 1
    assert chunks[0].context is None


def test_missing_grammar_falls_back_and_flags_the_fallback():
    """A language recognised by LANG_BY_EXT but with no installed tree-sitter
    grammar must still get SOME chunking (line windows) but the caller must be
    told this happened — the whole point of the honesty rule."""
    src = "\n".join(f"line {i}" for i in range(80))
    chunks = chunk_code(src, lang="not-a-real-language", **KW)
    assert chunks.fell_back is True
    assert len(chunks) >= 1


def test_supported_grammar_parse_does_not_flag_a_fallback():
    chunks = chunk_code("def f():\n    return 1\n", lang="python", **KW)
    assert chunks.fell_back is False


def test_a_file_with_no_definitions_is_NOT_flagged_as_a_grammar_fallback():
    """chunk_code's second fallback (spans-less -> chunk_text) is a legitimate
    'this file has no functions/classes' case (e.g. a constants module), not a
    degradation. Only the tree-sitter-unavailable path counts."""
    chunks = chunk_code("CONFIG = {'a': 1}\n", lang="python", **KW)
    assert chunks.fell_back is False


def test_missing_grammar_pack_falls_back_rather_than_raising_NameError(monkeypatch):
    """The pack not being installed at all must reach the line-window fallback.

    Naming the pack's own exception class in the `except` tuple is a trap: if
    the import that binds that name is the thing that failed, evaluating the
    tuple raises NameError and the fallback never runs — so the one environment
    the fallback exists for (no grammar pack, e.g. Windows) is the one where it
    breaks. Setting sys.modules[...] = None is the standard way to make an
    import genuinely fail without uninstalling anything.
    """
    import sys

    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    chunks = chunk_code(
        "def f():\n    return 1\n", source="s", rel_path="a.py", file_sha="x", lang="python"
    )
    assert chunks.fell_back is True
    assert len(chunks) > 0


def test_a_genuine_parser_crash_on_a_supported_grammar_is_not_swallowed(monkeypatch):
    """The bug this whole task exists to fix: a bare `except Exception` hid real
    tree-sitter crashes on supported languages behind a silent line-window
    fallback. Only 'grammar unavailable' conditions may be caught."""
    import tree_sitter_language_pack

    def boom(name):
        raise RuntimeError("simulated parser crash, not a missing-grammar condition")

    monkeypatch.setattr(tree_sitter_language_pack, "get_parser", boom)

    import pytest

    with pytest.raises(RuntimeError):
        chunk_code("def f():\n    return 1\n", lang="python", **KW)
