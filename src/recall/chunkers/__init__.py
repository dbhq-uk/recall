from recall.models import Chunk

MIN_CHUNK_CHARS = 200
MAX_CHUNK_CHARS = 2000
OVERLAP_CHARS = 150
CODE_WINDOW_LINES = 60
CODE_OVERLAP_LINES = 10

LANG_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".sh": "bash",
    ".bash": "bash",
}

MARKDOWN_EXTS = {".md", ".markdown", ".mdx"}


def chunk_file(text: str, *, source: str, rel_path: str, file_sha: str) -> list[Chunk]:
    """The single entry point. Routes by extension: markdown -> heading-aware,
    known code -> tree-sitter, everything else -> line windows."""
    from pathlib import PurePosixPath

    from recall.chunkers.code import chunk_code
    from recall.chunkers.markdown import chunk_markdown
    from recall.chunkers.text import chunk_text

    ext = PurePosixPath(rel_path).suffix.lower()

    if ext in MARKDOWN_EXTS:
        return chunk_markdown(text, source=source, rel_path=rel_path, file_sha=file_sha)
    if lang := LANG_BY_EXT.get(ext):
        return chunk_code(text, source=source, rel_path=rel_path, file_sha=file_sha, lang=lang)
    return chunk_text(text, source=source, rel_path=rel_path, file_sha=file_sha)
