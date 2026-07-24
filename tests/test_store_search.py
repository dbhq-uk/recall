import pytest

from recall.models import Chunk
from tests.conftest import requires_pg_search, requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]

DIM = 8


def vec(*first) -> list[float]:
    v = [0.0] * DIM
    for i, val in enumerate(first):
        v[i] = float(val)
    return v


def mk(rel_path, content, embedding, source="brain", idx=0) -> Chunk:
    return Chunk(
        source=source,
        rel_path=rel_path,
        chunk_idx=idx,
        content=content,
        context=None,
        lang="markdown",
        file_sha="sha",
        embedding=embedding,
    )


@pytest.fixture
def corpus(store_factory):
    def _load(store):
        store.upsert(
            [
                mk("van.md", "the van has a pop-top roof for sleeping", vec(1, 0, 0)),
                mk("pg.md", "postgres full text search and ranking", vec(0, 1, 0)),
                mk("fusion.md", "reciprocal rank fusion combines rankers", vec(0, 0, 1)),
                mk("other.md", "entirely unrelated prose about cheese", vec(0, 0, 0.5), idx=1),
            ]
        )
        return store

    return _load


# --- heading/symbol context is lexically searchable --------------------------
# The heading trail (prose) or symbol name (code) is folded into the lexical
# field, not just the embedding — otherwise a term that appears only in a heading
# is dense-findable but invisible to BM25/ts_rank_cd. Distinctive term in the
# context, absent from the body: it must still be retrievable by the lexical half.


def _heading_only_chunk() -> Chunk:
    return Chunk(
        source="brain",
        rel_path="doc.md",
        chunk_idx=0,
        content="the body mentions nothing distinctive at all",
        context="Zorblax Configuration",
        lang="markdown",
        file_sha="sha",
        embedding=vec(1, 0, 0),
    )


@requires_pg_search
def test_heading_context_is_lexically_searchable_with_bm25(store_factory):
    store = store_factory(dim=DIM, pg_search_enabled=True)
    store.upsert([_heading_only_chunk()])
    assert "doc.md" in store.search_lexical_only("Zorblax", ["brain"], limit=10)


def test_heading_context_is_lexically_searchable_with_ts_rank_cd(store_factory):
    store = store_factory(dim=DIM, pg_search_enabled=False)
    store.upsert([_heading_only_chunk()])
    assert "doc.md" in store.search_lexical_only("Zorblax", ["brain"], limit=10)


# --- both ranker paths -------------------------------------------------------


@requires_pg_search
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


@requires_pg_search
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


@requires_pg_search
def test_A_QUERY_WITH_A_COLON_DOES_NOT_EXPLODE_UNDER_BM25(store_factory, corpus):
    """Bare `@@@ 'text'` parses its RHS as a query DSL and raises on a colon.
    paradedb.match takes it as terms. This test is the regression guard."""
    store = corpus(store_factory(dim=DIM, pg_search_enabled=True))
    r = store.search(
        qvec=vec(1, 0, 0), qtext="how do I use foo: bar", sources=["brain"], limit=10, k=60
    )
    assert isinstance(r.hits, list)  # did not raise


@requires_pg_search
@pytest.mark.parametrize(
    "hostile",
    [
        'unbalanced "quote',
        "unclosed (paren",
        "AND OR NOT",
        "colon: and more: colons:",
        "",
        "   ",
    ],
)
def test_hostile_queries_do_not_raise_under_either_ranker(store_factory, corpus, hostile):
    """Both rankers, in one test — so it needs the real extension, not just the
    fallback. The ts_rank_cd-only hostile-input coverage lives implicitly in
    every other fallback test in this module, which all use hostile-adjacent
    real queries too."""
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
    store.upsert(
        [
            mk("a.md", "alpha alpha alpha", vec(1, 0, 0)),
            mk("b.md", "beta beta beta", vec(0.9, 0.1, 0)),
            mk("c.md", "reciprocal rank fusion combines rankers", vec(0.8, 0.2, 0)),
        ]
    )
    r = store.search(
        qvec=vec(1, 0, 0), qtext="reciprocal fusion", sources=["brain"], limit=10, k=60
    )
    c = [h for h in r.hits if h.rel_path == "c.md"][0]
    assert c.dense_rank == 3
    assert c.lexical_rank == 1
    assert c.score == pytest.approx(1 / 63 + 1 / 61, rel=1e-9)


def test_a_doc_both_halves_found_beats_a_doc_only_one_found(store_factory):
    """The entire justification for fusing at all."""
    store = store_factory(dim=DIM, pg_search_enabled=False)
    store.upsert(
        [
            mk("dense_only.md", "nothing lexical here at all", vec(1, 0, 0)),
            mk("both.md", "reciprocal rank fusion", vec(0.7, 0.3, 0)),
        ]
    )
    r = store.search(
        qvec=vec(1, 0, 0), qtext="reciprocal rank fusion", sources=["brain"], limit=10, k=60
    )
    ranked = [h.rel_path for h in r.hits]
    assert ranked.index("both.md") < ranked.index("dense_only.md")


def test_w_dense_1_w_lexical_0_reproduces_dense_only_ranking(store_factory, corpus):
    """The convex combination is a generalisation: at the w_dense=1/w_lexical=0
    extreme, the lexical half contributes nothing and the fused ranking must
    match the dense-only ranking exactly."""
    store = corpus(store_factory(dim=DIM, pg_search_enabled=False))
    qvec = vec(0, 0, 1)
    fused = store.search(
        qvec=qvec,
        qtext="postgres ranking",
        sources=["brain"],
        limit=10,
        k=60,
        w_dense=1.0,
        w_lexical=0.0,
    )
    dense_only = store.search_dense_only(qvec=qvec, sources=["brain"], limit=10)
    assert [h.rel_path for h in fused.hits] == dense_only


def test_w_dense_0_w_lexical_1_reproduces_lexical_only_ranking(store_factory):
    """Mirror of the above: at the w_dense=0/w_lexical=1 extreme, the dense half
    contributes nothing and the fused ranking must match the lexical-only
    ranking exactly.

    This needs its own corpus rather than the shared `corpus` fixture: the
    dense CTE has no relevance threshold and always returns its full pool, so
    if any candidate matched dense but NOT the lexical query, it would still
    be smuggled into the fused result at score 0 (COALESCE'd from a NULL
    lexical rank) — something search_lexical_only, which only returns real
    matches, would never do. Every doc here matches the lexical query too, so
    that smuggling can't happen and the two rankings must line up exactly.
    """
    store = store_factory(dim=DIM, pg_search_enabled=False)
    store.upsert(
        [
            mk("c.md", "postgres ranking postgres ranking postgres ranking extra", vec(0, 0, 1)),
            mk("b.md", "postgres ranking postgres extra", vec(0, 1, 0)),
            mk("a.md", "postgres ranking extra", vec(1, 0, 0)),
        ]
    )
    fused = store.search(
        qvec=vec(0, 0, 1),
        qtext="postgres ranking",
        sources=["brain"],
        limit=10,
        k=60,
        w_dense=0.0,
        w_lexical=1.0,
    )
    lexical_only = store.search_lexical_only(qtext="postgres ranking", sources=["brain"], limit=10)
    assert [h.rel_path for h in fused.hits] == lexical_only
    assert lexical_only == ["c.md", "b.md", "a.md"]  # sanity: the ranks genuinely differ


def test_fusion_weights_change_the_ordering(store_factory):
    """A doc strong in dense but weak in lexical must rank higher under a
    dense-leaning weighting than under equal weighting — this is the entire
    point of making the weights configurable.

    k=1 here (not the store/config default) is deliberate: it sharpens the
    gap between dense rank 1 and rank 2 enough that a 0.9/0.1 split can
    actually flip the ordering relative to 1.0/1.0. This is a mechanism test,
    not a claim about production k or the shipped default weights.
    """
    store = store_factory(dim=DIM, pg_search_enabled=False)
    store.upsert(
        [
            # Dense rank 1 (exact vector match). "fusion" alone does not
            # satisfy the AND query "reciprocal & rank & fusion", so this
            # doc gets no lexical match at all (l.rank is NULL, contributes 0).
            mk("dense_favourite.md", "fusion", vec(1, 0, 0)),
            # Dense rank 2 (far vector), the only lexical match (rank 1).
            mk(
                "lexical_favourite.md",
                "reciprocal rank fusion reciprocal rank fusion",
                vec(0, 0, 1),
            ),
        ]
    )
    equal = store.search(
        qvec=vec(1, 0, 0),
        qtext="reciprocal rank fusion",
        sources=["brain"],
        limit=10,
        k=1,
        w_dense=1.0,
        w_lexical=1.0,
    )
    dense_leaning = store.search(
        qvec=vec(1, 0, 0),
        qtext="reciprocal rank fusion",
        sources=["brain"],
        limit=10,
        k=1,
        w_dense=0.9,
        w_lexical=0.1,
    )
    equal_order = [h.rel_path for h in equal.hits]
    dense_leaning_order = [h.rel_path for h in dense_leaning.hits]
    assert equal_order.index("lexical_favourite.md") < equal_order.index("dense_favourite.md")
    assert dense_leaning_order.index("dense_favourite.md") < dense_leaning_order.index(
        "lexical_favourite.md"
    )


def test_k_is_a_knob_and_changing_it_changes_the_ranking(store_factory):
    """Design: k=60 is a convention, not a law. Let the golden set decide."""
    store = store_factory(dim=DIM, pg_search_enabled=False)
    store.upsert(
        [
            mk("a.md", "alpha", vec(1, 0, 0)),
            mk("b.md", "reciprocal rank fusion", vec(0.1, 0.9, 0)),
        ]
    )
    tight = store.search(
        qvec=vec(1, 0, 0), qtext="reciprocal rank fusion", sources=["brain"], limit=10, k=1
    )
    loose = store.search(
        qvec=vec(1, 0, 0), qtext="reciprocal rank fusion", sources=["brain"], limit=10, k=1000
    )
    assert tight.hits[0].score != loose.hits[0].score


# --- silos -------------------------------------------------------------------


def test_search_is_siloed_by_default(store_factory):
    store = store_factory(dim=DIM)
    store.upsert(
        [
            mk("a.md", "shared word here", vec(1, 0, 0), source="brain"),
            mk("b.md", "shared word here", vec(1, 0, 0), source="dbhq"),
        ]
    )
    r = store.search(qvec=vec(1, 0, 0), qtext="shared word", sources=["brain"], limit=10, k=60)
    assert {h.source for h in r.hits} == {"brain"}


def test_star_spans_every_silo(store_factory):
    store = store_factory(dim=DIM)
    store.upsert(
        [
            mk("a.md", "shared word here", vec(1, 0, 0), source="brain"),
            mk("b.md", "shared word here", vec(1, 0, 0), source="dbhq"),
        ]
    )
    r = store.search(qvec=vec(1, 0, 0), qtext="shared word", sources=["*"], limit=10, k=60)
    assert {h.source for h in r.hits} == {"brain", "dbhq"}


def test_search_can_span_a_named_subset_of_silos(store_factory):
    store = store_factory(dim=DIM)
    store.upsert(
        [
            mk("a.md", "word", vec(1, 0, 0), source="brain"),
            mk("b.md", "word", vec(1, 0, 0), source="dbhq"),
            mk("c.md", "word", vec(1, 0, 0), source="other"),
        ]
    )
    r = store.search(qvec=vec(1, 0, 0), qtext="word", sources=["brain", "dbhq"], limit=10, k=60)
    assert {h.source for h in r.hits} == {"brain", "dbhq"}


def test_limit_is_respected(store_factory):
    store = store_factory(dim=DIM)
    store.upsert([mk(f"{i}.md", f"word {i}", vec(1, 0, 0), idx=i) for i in range(10)])
    r = store.search(qvec=vec(1, 0, 0), qtext="word", sources=["brain"], limit=3, k=60)
    assert len(r.hits) == 3


def test_searching_an_empty_store_returns_nothing_rather_than_raising(store_factory):
    store = store_factory(dim=DIM)
    r = store.search(qvec=vec(1, 0, 0), qtext="anything", sources=["*"], limit=10, k=60)
    assert r.hits == []


def test_hits_carry_the_context_so_results_display_without_reparsing(store_factory):
    store = store_factory(dim=DIM)
    store.upsert(
        [
            Chunk(
                source="brain",
                rel_path="van.md",
                chunk_idx=0,
                content="the pop-top",
                context="Areas > Travel > Van",
                lang="markdown",
                file_sha="s",
                embedding=vec(1, 0, 0),
            ),
        ]
    )
    r = store.search(qvec=vec(1, 0, 0), qtext="pop-top", sources=["brain"], limit=10, k=60)
    assert r.hits[0].context == "Areas > Travel > Van"
    assert r.hits[0].chunk_id == "brain:van.md:0"


# --- eval-support: the unfused halves, for eval/harness.py -------------------
#
# These exist so the golden-query harness can score each arm against its own
# true top-limit ranking rather than deriving a baseline by re-sorting the
# fused pool (biased: the fused result only contains docs that survived
# fusion). Not part of the Store protocol used at request time.


def test_search_dense_only_returns_the_true_top_by_cosine_distance(store_factory, corpus):
    store = corpus(store_factory(dim=DIM, pg_search_enabled=False))
    ranking = store.search_dense_only(qvec=vec(1, 0, 0), sources=["brain"], limit=10)
    assert isinstance(ranking, list)
    assert all(isinstance(p, str) for p in ranking)
    assert ranking[0] == "van.md"
    assert len(ranking) == 4  # every chunk in the corpus, just ordered by distance


def test_search_dense_only_respects_limit(store_factory, corpus):
    store = corpus(store_factory(dim=DIM, pg_search_enabled=False))
    ranking = store.search_dense_only(qvec=vec(1, 0, 0), sources=["brain"], limit=2)
    assert len(ranking) == 2
    assert ranking[0] == "van.md"


def test_search_dense_only_is_siloed(store_factory):
    store = store_factory(dim=DIM)
    store.upsert(
        [
            mk("a.md", "shared word here", vec(1, 0, 0), source="brain"),
            mk("b.md", "shared word here", vec(1, 0, 0), source="dbhq"),
        ]
    )
    ranking = store.search_dense_only(qvec=vec(1, 0, 0), sources=["brain"], limit=10)
    assert ranking == ["a.md"]


def test_search_dense_only_on_no_resolved_sources_returns_empty_list(store_factory):
    store = store_factory(dim=DIM)
    assert store.search_dense_only(qvec=vec(1, 0, 0), sources=[], limit=10) == []


@requires_pg_search
def test_search_lexical_only_matches_the_live_ranker_REAL_BM25(store_factory, corpus):
    store = corpus(store_factory(dim=DIM, pg_search_enabled=True))
    assert store.lexical_ranker() == "bm25"
    ranking = store.search_lexical_only(qtext="pop-top roof", sources=["brain"], limit=10)
    assert ranking[0] == "van.md"
    # only docs the ranker actually matched come back, not the whole corpus
    assert "fusion.md" not in ranking


def test_search_lexical_only_matches_the_live_ranker_TS_RANK_CD_FALLBACK(store_factory, corpus):
    store = corpus(store_factory(dim=DIM, pg_search_enabled=False))
    assert store.lexical_ranker() == "ts_rank_cd"
    ranking = store.search_lexical_only(qtext="pop-top roof", sources=["brain"], limit=10)
    assert ranking[0] == "van.md"
    assert "fusion.md" not in ranking


def test_search_lexical_only_respects_limit(store_factory):
    store = store_factory(dim=DIM, pg_search_enabled=False)
    store.upsert([mk(f"{i}.md", f"shared word {i}", vec(1, 0, 0), idx=i) for i in range(5)])
    ranking = store.search_lexical_only(qtext="shared word", sources=["brain"], limit=3)
    assert len(ranking) == 3


def test_search_lexical_only_is_siloed(store_factory):
    store = store_factory(dim=DIM, pg_search_enabled=False)
    store.upsert(
        [
            mk("a.md", "shared word here", vec(1, 0, 0), source="brain"),
            mk("b.md", "shared word here", vec(1, 0, 0), source="dbhq"),
        ]
    )
    ranking = store.search_lexical_only(qtext="shared word", sources=["brain"], limit=10)
    assert ranking == ["a.md"]


def test_search_lexical_only_on_no_resolved_sources_returns_empty_list(store_factory):
    store = store_factory(dim=DIM)
    assert store.search_lexical_only(qtext="anything", sources=[], limit=10) == []


@requires_pg_search
def test_search_lexical_only_DOES_NOT_EXPLODE_ON_A_COLON_under_bm25(store_factory, corpus):
    """Same regression this product's fusion query already guards: bare `@@@`
    parses user text as pg_search's query DSL and raises on a colon.
    search_lexical_only must go through paradedb.match, same as fusion does."""
    store = corpus(store_factory(dim=DIM, pg_search_enabled=True))
    ranking = store.search_lexical_only(qtext="how do I use foo: bar", sources=["brain"], limit=10)
    assert isinstance(ranking, list)  # did not raise


def test_search_lexical_only_with_no_hits_returns_empty_list(store_factory, corpus):
    store = corpus(store_factory(dim=DIM, pg_search_enabled=False))
    ranking = store.search_lexical_only(qtext="zzzznotawordanywhere", sources=["brain"], limit=10)
    assert ranking == []


# --- limit validation ---------------------------------------------------------
#
# limit=0 used to silently return zero results — indistinguishable from "no
# matches". A negative limit reached raw SQL and raised an opaque psycopg
# error. Both are the silent/opaque failure mode this product exists to catch.


def test_search_rejects_a_zero_limit(store_factory):
    from recall.errors import InvalidLimitError

    store = store_factory(dim=DIM)
    with pytest.raises(InvalidLimitError, match="0"):
        store.search(qvec=vec(1, 0, 0), qtext="word", sources=["brain"], limit=0)


def test_search_rejects_a_negative_limit(store_factory):
    from recall.errors import InvalidLimitError

    store = store_factory(dim=DIM)
    with pytest.raises(InvalidLimitError, match="-1"):
        store.search(qvec=vec(1, 0, 0), qtext="word", sources=["brain"], limit=-1)


def test_search_rejects_a_limit_above_the_maximum(store_factory):
    from recall.errors import InvalidLimitError
    from recall.store.pgvector import PgVectorStore

    store = store_factory(dim=DIM)
    too_big = PgVectorStore.MAX_LIMIT + 1
    with pytest.raises(InvalidLimitError, match=str(too_big)):
        store.search(qvec=vec(1, 0, 0), qtext="word", sources=["brain"], limit=too_big)


def test_search_dense_only_rejects_an_invalid_limit(store_factory):
    from recall.errors import InvalidLimitError

    store = store_factory(dim=DIM)
    with pytest.raises(InvalidLimitError):
        store.search_dense_only(qvec=vec(1, 0, 0), sources=["brain"], limit=0)


def test_search_lexical_only_rejects_an_invalid_limit(store_factory):
    from recall.errors import InvalidLimitError

    store = store_factory(dim=DIM)
    with pytest.raises(InvalidLimitError):
        store.search_lexical_only(qtext="word", sources=["brain"], limit=0)


# --- one connection per logical search ----------------------------------------


def test_search_opens_exactly_one_connection(store_factory, corpus, monkeypatch):
    """search() used to open three separate connections (lexical_ranker(),
    _resolve_sources(), and the search statement itself). One logical query
    should cost one connection."""
    import psycopg

    store = corpus(store_factory(dim=DIM, pg_search_enabled=False))

    real_connect = psycopg.connect
    calls = []

    def counting_connect(*args, **kwargs):
        calls.append(1)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", counting_connect)
    store.search(qvec=vec(1, 0, 0), qtext="pop-top roof", sources=["*"], limit=10, k=60)
    assert len(calls) == 1
