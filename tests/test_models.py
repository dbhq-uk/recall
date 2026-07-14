from recall.models import Chunk, SearchResult, SearchHit


def test_chunk_id_is_tag_addressed_never_path_addressed():
    c = Chunk(
        source="brain", rel_path="notes/van.md", chunk_idx=2,
        content="the pop-top goes up", context="Areas > Travel > Van",
        lang="markdown", file_sha="abc123",
    )
    assert c.chunk_id == "brain:notes/van.md:2"


def test_embed_text_prepends_heading_trail():
    """The design's central chunking claim: the trail is embedded, not just stored."""
    c = Chunk(
        source="brain", rel_path="notes/van.md", chunk_idx=0,
        content="we went with the pop-top", context="Areas > Travel > Van > Decision",
        lang="markdown", file_sha="abc",
    )
    assert c.embed_text == "Areas > Travel > Van > Decision\n\nwe went with the pop-top"


def test_embed_text_without_context_is_just_content():
    c = Chunk(
        source="brain", rel_path="a.txt", chunk_idx=0,
        content="bare text", context=None, lang=None, file_sha="abc",
    )
    assert c.embed_text == "bare text"


def test_search_result_flags_dense_only_when_lexical_half_is_empty():
    """A hybrid search that quietly became dense-only must never look healthy."""
    r = SearchResult(hits=[], lexical_ranker="bm25", dense_hit_count=5, lexical_hit_count=0)
    assert r.is_hybrid is False
    assert any("dense-only" in n for n in r.notes)


def test_search_result_flags_the_fallback_ranker():
    r = SearchResult(hits=[], lexical_ranker="ts_rank_cd", dense_hit_count=5, lexical_hit_count=3)
    assert any("ts_rank_cd" in n and "not BM25" in n for n in r.notes)


def test_search_result_clean_hybrid_has_no_notes():
    r = SearchResult(hits=[], lexical_ranker="bm25", dense_hit_count=5, lexical_hit_count=3)
    assert r.is_hybrid is True
    assert r.notes == []
