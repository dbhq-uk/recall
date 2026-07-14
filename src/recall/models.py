from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LexicalRanker = Literal["bm25", "ts_rank_cd"]


@dataclass(frozen=True)
class Chunk:
    """One indexed passage.

    Identity is ``{tag}:{rel_path}:{chunk_idx}``. There is deliberately no
    absolute path here, and there must never be one: an index has to survive
    the source moving to a different machine or a different path.
    """

    source: str
    rel_path: str
    chunk_idx: int
    content: str
    context: str | None
    lang: str | None
    file_sha: str
    embedding: list[float] | None = None

    @property
    def chunk_id(self) -> str:
        return f"{self.source}:{self.rel_path}:{self.chunk_idx}"

    @property
    def embed_text(self) -> str:
        """What actually gets embedded.

        The heading trail (prose) or symbol name (code) is prepended, so that a
        chunk reading "we went with the pop-top" embeds as
        "Areas > Travel > Van > Decision\\n\\nwe went with the pop-top".
        Without this a passage loses the context that makes it findable.
        """
        if self.context:
            return f"{self.context}\n\n{self.content}"
        return self.content


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    source: str
    rel_path: str
    chunk_idx: int
    context: str | None
    content: str
    lang: str | None
    score: float
    dense_rank: int | None
    lexical_rank: int | None


@dataclass
class SearchResult:
    hits: list[SearchHit]
    lexical_ranker: LexicalRanker
    dense_hit_count: int
    lexical_hit_count: int
    notes: list[str] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        if self.lexical_ranker == "ts_rank_cd":
            self.notes.append(
                "Lexical half is ranked by ts_rank_cd, which is not BM25: it has no "
                "term-frequency saturation and no document-length normalisation. "
                "Install the pg_search extension for real BM25."
            )
        if self.lexical_hit_count == 0:
            self.notes.append(
                "The lexical half returned no hits. These are dense-only results, "
                "NOT hybrid results. Do not read them as a hybrid ranking."
            )

    @property
    def is_hybrid(self) -> bool:
        """True only when both halves actually contributed."""
        return self.dense_hit_count > 0 and self.lexical_hit_count > 0


@dataclass(frozen=True)
class Stats:
    sources: dict[str, int]
    total_chunks: int
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    lexical_ranker: LexicalRanker
    backend: str = "pgvector"
