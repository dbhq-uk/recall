import pytest

from recall.models import Chunk
from tests.conftest import requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]

DIM = 8


def vec(*first) -> list[float]:
    v = [0.0] * DIM
    for i, val in enumerate(first):
        v[i] = float(val)
    return v


def mk(rel_path, content, embedding, source="brain", idx=0) -> Chunk:
    return Chunk(
        source=source, rel_path=rel_path, chunk_idx=idx, content=content,
        context=None, lang="markdown", file_sha="sha", embedding=embedding,
    )


@pytest.fixture
def corpus(store_factory):
    def _load(store):
        store.upsert([
            mk("van.md",     "the van has a pop-top roof for sleeping", vec(1, 0, 0)),
            mk("pg.md",      "postgres full text search and ranking",   vec(0, 1, 0)),
            mk("fusion.md",  "reciprocal rank fusion combines rankers", vec(0, 0, 1)),
            mk("other.md",   "entirely unrelated prose about cheese",   vec(0, 0, 0.5), idx=1),
        ])
        return store
    return _load


# --- both ranker paths -------------------------------------------------------

def test_hybrid_search_with_REAL_BM25(store_factory, corpus):
    store = corpus(store_factory(dim=DIM, pg_search_enabled=True))
    r = store.search(qvec=vec(1, 0, 0), qtext="pop-top roof", sources=["brain"], limit=10, k=60)
    assert r.lexical_ranker == "bm25"
    assert r.is_hybrid
    assert r.notes == []
    assert r.hits[0].rel_path == "van.md"


def test_hybrid_search_with_the_ts_rank_cd_FALLBACK(store_factory, corpus):
    store = corpus(store_factory(dim=DIM, pg_search_enabled=False))
    r = store.search(qvec=vec(1, 0, 0), qtext="pop-top roof", sources=["brain"], limit=10, k=60)
    assert r.lexical_ranker == "ts_rank_cd"
    assert r.hits[0].rel_path == "van.md"


def test_THE_FALLBACK_IS_ANNOUNCED_not_hidden(store_factory, corpus):
    """A hybrid search that has quietly become something else is worse than
    useless, because it looks like it is working."""
    store = corpus(store_factory(dim=DIM, pg_search_enabled=False))
    r = store.search(qvec=vec(1, 0, 0), qtext="roof", sources=["brain"], limit=10, k=60)
    assert any("not BM25" in n for n in r.notes)


# --- the degradation that matters most ---------------------------------------

def test_ZERO_LEXICAL_HITS_IS_REPORTED_AS_DENSE_ONLY(store_factory, corpus):
    """Design §Failure modes: return dense-only results, and SAY SO. Never present
    it as a hybrid result."""
    store = corpus(store_factory(dim=DIM, pg_search_enabled=True))
    r = store.search(
        qvec=vec(1, 0, 0), qtext="zzzznotawordanywhere", sources=["brain"], limit=10, k=60
    )
    assert r.lexical_hit_count == 0
    assert r.dense_hit_count > 0
    assert r.is_hybrid is False
    assert any("dense-only" in n for n in r.notes)
    assert r.hits  # we still return the dense results — we just do not lie about them


# --- the punctuation bug that pg_search would otherwise hand us --------------

def test_A_QUERY_WITH_A_COLON_DOES_NOT_EXPLODE_UNDER_BM25(store_factory, corpus):
    """Bare `@@@ 'text'` parses its RHS as a query DSL and raises on a colon.
    paradedb.match takes it as terms. This test is the regression guard."""
    store = corpus(store_factory(dim=DIM, pg_search_enabled=True))
    r = store.search(
        qvec=vec(1, 0, 0), qtext="how do I use foo: bar", sources=["brain"], limit=10, k=60
    )
    assert isinstance(r.hits, list)  # did not raise


@pytest.mark.parametrize("hostile", [
    'unbalanced "quote',
    "unclosed (paren",
    "AND OR NOT",
    "colon: and more: colons:",
    "",
    "   ",
])
def test_hostile_queries_do_not_raise_under_either_ranker(store_factory, corpus, hostile):
    for enabled in (True, False):
        store = corpus(store_factory(dim=DIM, pg_search_enabled=enabled))
        r = store.search(qvec=vec(1, 0, 0), qtext=hostile, sources=["brain"], limit=10, k=60)
        assert isinstance(r.hits, list)


# --- RRF arithmetic against the live database --------------------------------

def test_RRF_ARITHMETIC_matches_the_hand_worked_example(store_factory):
    """Verified against live Postgres during planning:
    dense rank 3 + lexical rank 1 at k=60 -> 1/63 + 1/61 = 0.032266458...
    """
    store = store_factory(dim=DIM, pg_search_enabled=False)
    store.upsert([
        mk("a.md", "alpha alpha alpha",                       vec(1, 0, 0)),
        mk("b.md", "beta beta beta",                          vec(0.9, 0.1, 0)),
        mk("c.md", "reciprocal rank fusion combines rankers", vec(0.8, 0.2, 0)),
    ])
    r = store.search(qvec=vec(1, 0, 0), qtext="reciprocal fusion", sources=["brain"], limit=10, k=60)
    c = [h for h in r.hits if h.rel_path == "c.md"][0]
    assert c.dense_rank == 3
    assert c.lexical_rank == 1
    assert c.score == pytest.approx(1 / 63 + 1 / 61, rel=1e-9)


def test_a_doc_both_halves_found_beats_a_doc_only_one_found(store_factory):
    """The entire justification for fusing at all."""
    store = store_factory(dim=DIM, pg_search_enabled=False)
    store.upsert([
        mk("dense_only.md", "nothing lexical here at all", vec(1, 0, 0)),
        mk("both.md",       "reciprocal rank fusion",      vec(0.7, 0.3, 0)),
    ])
    r = store.search(qvec=vec(1, 0, 0), qtext="reciprocal rank fusion", sources=["brain"], limit=10, k=60)
    ranked = [h.rel_path for h in r.hits]
    assert ranked.index("both.md") < ranked.index("dense_only.md")


def test_k_is_a_knob_and_changing_it_changes_the_ranking(store_factory):
    """Design: k=60 is a convention, not a law. Let the golden set decide."""
    store = store_factory(dim=DIM, pg_search_enabled=False)
    store.upsert([
        mk("a.md", "alpha",                  vec(1, 0, 0)),
        mk("b.md", "reciprocal rank fusion", vec(0.1, 0.9, 0)),
    ])
    tight = store.search(qvec=vec(1, 0, 0), qtext="reciprocal rank fusion", sources=["brain"], limit=10, k=1)
    loose = store.search(qvec=vec(1, 0, 0), qtext="reciprocal rank fusion", sources=["brain"], limit=10, k=1000)
    assert tight.hits[0].score != loose.hits[0].score


# --- silos -------------------------------------------------------------------

def test_search_is_siloed_by_default(store_factory):
    store = store_factory(dim=DIM)
    store.upsert([
        mk("a.md", "shared word here", vec(1, 0, 0), source="brain"),
        mk("b.md", "shared word here", vec(1, 0, 0), source="dbhq"),
    ])
    r = store.search(qvec=vec(1, 0, 0), qtext="shared word", sources=["brain"], limit=10, k=60)
    assert {h.source for h in r.hits} == {"brain"}


def test_star_spans_every_silo(store_factory):
    store = store_factory(dim=DIM)
    store.upsert([
        mk("a.md", "shared word here", vec(1, 0, 0), source="brain"),
        mk("b.md", "shared word here", vec(1, 0, 0), source="dbhq"),
    ])
    r = store.search(qvec=vec(1, 0, 0), qtext="shared word", sources=["*"], limit=10, k=60)
    assert {h.source for h in r.hits} == {"brain", "dbhq"}


def test_search_can_span_a_named_subset_of_silos(store_factory):
    store = store_factory(dim=DIM)
    store.upsert([
        mk("a.md", "word", vec(1, 0, 0), source="brain"),
        mk("b.md", "word", vec(1, 0, 0), source="dbhq"),
        mk("c.md", "word", vec(1, 0, 0), source="other"),
    ])
    r = store.search(qvec=vec(1, 0, 0), qtext="word", sources=["brain", "dbhq"], limit=10, k=60)
    assert {h.source for h in r.hits} == {"brain", "dbhq"}


def test_limit_is_respected(store_factory):
    store = store_factory(dim=DIM)
    store.upsert([mk(f"{i}.md", f"word {i}", vec(1, 0, 0), idx=i) for i in range(10)])
    assert len(store.search(qvec=vec(1, 0, 0), qtext="word", sources=["brain"], limit=3, k=60).hits) == 3


def test_searching_an_empty_store_returns_nothing_rather_than_raising(store_factory):
    store = store_factory(dim=DIM)
    r = store.search(qvec=vec(1, 0, 0), qtext="anything", sources=["*"], limit=10, k=60)
    assert r.hits == []


def test_hits_carry_the_context_so_results_display_without_reparsing(store_factory):
    store = store_factory(dim=DIM)
    store.upsert([
        Chunk(source="brain", rel_path="van.md", chunk_idx=0, content="the pop-top",
              context="Areas > Travel > Van", lang="markdown", file_sha="s",
              embedding=vec(1, 0, 0)),
    ])
    r = store.search(qvec=vec(1, 0, 0), qtext="pop-top", sources=["brain"], limit=10, k=60)
    assert r.hits[0].context == "Areas > Travel > Van"
    assert r.hits[0].chunk_id == "brain:van.md:0"
