"""Fast, pure unit tests for eval/beir.py.

No network, no database, no indexing. run_dataset and main()'s --index path
are the slow/real path (real store, real embedder) and are deliberately not
exercised here -- see eval/beir.py's module docstring.
"""

from __future__ import annotations

import tomllib

import pytest

from eval.beir import (
    PUBLISHED_BASELINES,
    doc_id_from_rel_path,
    evaluate_run,
    load_corpus,
    load_qrels,
    load_queries,
    materialise_corpus,
    pool_chunks_to_docs,
    print_report,
    ranked_run_from_paths,
)

# ---------------------------------------------------------------------------
# load_corpus
# ---------------------------------------------------------------------------


def test_load_corpus_parses_id_title_text(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text(
        '{"_id": "1", "title": "A title", "text": "Some body text."}\n'
        '{"_id": "2", "title": "Another title", "text": "More body text."}\n'
    )
    corpus = load_corpus(path)
    assert corpus == {
        "1": {"title": "A title", "text": "Some body text."},
        "2": {"title": "Another title", "text": "More body text."},
    }


def test_load_corpus_skips_blank_lines(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text('{"_id": "1", "title": "T", "text": "X"}\n\n')
    assert list(load_corpus(path)) == ["1"]


# ---------------------------------------------------------------------------
# load_qrels
# ---------------------------------------------------------------------------


def test_load_qrels_skips_header_row(tmp_path):
    path = tmp_path / "test.tsv"
    path.write_text("query-id\tcorpus-id\tscore\n1\t100\t1\n1\t101\t0\n2\t200\t1\n")
    qrels = load_qrels(path)
    assert "query-id" not in qrels
    assert qrels == {"1": {"100": 1, "101": 0}, "2": {"200": 1}}


def test_load_qrels_parses_graded_scores(tmp_path):
    """NFCorpus qrels are graded (0, 1, 2), not just binary."""
    path = tmp_path / "test.tsv"
    path.write_text("query-id\tcorpus-id\tscore\nQ1\tD1\t2\n")
    qrels = load_qrels(path)
    assert qrels["Q1"]["D1"] == 2
    assert isinstance(qrels["Q1"]["D1"], int)


# ---------------------------------------------------------------------------
# load_queries -- the critical split-filtering gotcha.
# ---------------------------------------------------------------------------


def test_load_queries_filters_to_test_qids_only(tmp_path):
    """queries.jsonl holds every split. Only qids present in qrels are the
    test split -- this is THE gotcha the task exists to pin down."""
    path = tmp_path / "queries.jsonl"
    path.write_text(
        "\n".join(
            f'{{"_id": "{i}", "text": "query {i}", "metadata": {{}}}}' for i in range(5)
        )
        + "\n"
    )
    qrels = {"1": {"d1": 1}, "3": {"d2": 1}}
    queries = load_queries(path, qrels)
    assert len(queries) == 2
    assert set(queries) == {"1", "3"}
    assert queries["1"] == "query 1"
    assert queries["3"] == "query 3"


def test_load_queries_empty_qrels_yields_no_queries(tmp_path):
    path = tmp_path / "queries.jsonl"
    path.write_text('{"_id": "1", "text": "query 1", "metadata": {}}\n')
    assert load_queries(path, {}) == {}


# ---------------------------------------------------------------------------
# materialise_corpus / doc_id_from_rel_path -- round trip.
# ---------------------------------------------------------------------------


def test_materialise_corpus_writes_one_md_file_per_doc(tmp_path):
    corpus = {
        "4983": {"title": "A title", "text": "Body text."},
        "d-2": {"title": "", "text": "No title doc."},
    }
    out_dir = tmp_path / "corpus"
    materialise_corpus(corpus, out_dir, tag="beir-test")

    assert (out_dir / "4983.md").read_text() == "# A title\n\nBody text.\n"
    assert (out_dir / "d-2.md").read_text() == "# \n\nNo title doc.\n"


def test_materialise_corpus_writes_recall_toml_with_given_tag(tmp_path):
    out_dir = tmp_path / "corpus"
    materialise_corpus({"1": {"title": "T", "text": "X"}}, out_dir, tag="beir-scifact")

    marker = tomllib.loads((out_dir / ".recall.toml").read_text())
    assert marker["source"]["tag"] == "beir-scifact"
    assert marker["source"]["include"] == ["**/*.md"]


def test_doc_id_from_rel_path_round_trips_with_materialise_corpus(tmp_path):
    corpus = {"4983": {"title": "T", "text": "X"}, "MED-123": {"title": "T2", "text": "Y"}}
    out_dir = tmp_path / "corpus"
    materialise_corpus(corpus, out_dir, tag="beir-test")

    for doc_id in corpus:
        rel_path = f"{doc_id}.md"
        assert (out_dir / rel_path).exists()
        assert doc_id_from_rel_path(rel_path) == doc_id


def test_doc_id_from_rel_path_strips_a_directory_prefix():
    assert doc_id_from_rel_path("sub/dir/4983.md") == "4983"


# ---------------------------------------------------------------------------
# pool_chunks_to_docs -- the most important test. MAX-pooling, not sum/mean.
# ---------------------------------------------------------------------------


class _FakeScoredHit:
    def __init__(self, rel_path: str, score: float) -> None:
        self.rel_path = rel_path
        self.score = score


def test_pool_chunks_to_docs_max_pools_across_chunks_of_the_same_doc():
    hits = [
        _FakeScoredHit("A.md", 0.2),
        _FakeScoredHit("B.md", 0.5),
        _FakeScoredHit("A.md", 0.9),
    ]
    assert pool_chunks_to_docs(hits) == {"A": 0.9, "B": 0.5}


def test_pool_chunks_to_docs_does_not_sum_the_chunks():
    """Pin the bug this test exists to prevent: summing (0.2 + 0.9 = 1.1)
    would let a doc win purely for having many mediocre chunks."""
    hits = [_FakeScoredHit("A.md", 0.2), _FakeScoredHit("A.md", 0.9)]
    result = pool_chunks_to_docs(hits)
    assert result["A"] == pytest.approx(0.9)
    assert result["A"] != pytest.approx(1.1)


def test_pool_chunks_to_docs_empty_input():
    assert pool_chunks_to_docs([]) == {}


# ---------------------------------------------------------------------------
# ranked_run_from_paths -- order preserved, deduped keeping best rank.
# ---------------------------------------------------------------------------


def test_ranked_run_from_paths_preserves_order():
    run = ranked_run_from_paths(["a.md", "b.md", "c.md"])
    ranked = sorted(run, key=lambda doc_id: -run[doc_id])
    assert ranked == ["a", "b", "c"]
    assert run["a"] > run["b"] > run["c"]


def test_ranked_run_from_paths_dedups_keeping_the_best_rank():
    run = ranked_run_from_paths(["a.md", "b.md", "a.md", "c.md"])
    assert set(run) == {"a", "b", "c"}
    # a.md's first (best) occurrence is rank 0 -- its score must reflect that,
    # not the later, worse occurrence at rank 2.
    assert run["a"] == pytest.approx(1.0)
    assert run["a"] > run["b"] > run["c"]


def test_ranked_run_from_paths_empty_input():
    assert ranked_run_from_paths([]) == {}


# ---------------------------------------------------------------------------
# evaluate_run -- hand-checkable NDCG@10.
# ---------------------------------------------------------------------------


def test_evaluate_run_ndcg_hand_checkable():
    """qrels: d1 and d2 both relevant. run ranks d1, d3(irrelevant), d2.

    DCG  = 1/log2(2) + 0/log2(3) + 1/log2(4) = 1 + 0 + 0.5 = 1.5
    IDCG = 1/log2(2) + 1/log2(3)             = 1 + 0.6309... = 1.6309...
    NDCG = 1.5 / 1.6309... = 0.91972...
    """
    qrels = {"q1": {"d1": 1, "d2": 1}}
    run = {"q1": {"d1": 3.0, "d3": 2.0, "d2": 1.0}}
    scores = evaluate_run(qrels, run, k=10)
    assert scores["ndcg@10"] == pytest.approx(0.9197207891481876)
    assert scores["recall@10"] == pytest.approx(1.0)
    assert scores["mrr"] == pytest.approx(1.0)


def test_evaluate_run_perfect_ranking_scores_one():
    qrels = {"q1": {"d1": 1}}
    run = {"q1": {"d1": 5.0, "d2": 1.0}}
    scores = evaluate_run(qrels, run, k=10)
    assert scores["ndcg@10"] == pytest.approx(1.0)


def test_evaluate_run_tolerates_a_query_with_no_hits_at_all():
    """An arm can legitimately return nothing for a query -- evaluate_run
    must not crash, it must just score that query as a miss."""
    qrels = {"q1": {"d1": 1}, "q2": {"d2": 1}}
    run = {"q1": {"d1": 1.0}, "q2": {}}
    scores = evaluate_run(qrels, run, k=10)
    assert 0.0 < scores["ndcg@10"] < 1.0


# ---------------------------------------------------------------------------
# print_report -- smoke test that it runs and names the published baselines.
# ---------------------------------------------------------------------------


def test_print_report_includes_published_baselines(capsys):
    arm_scores = {
        "dense": {"ndcg@10": 0.50, "recall@10": 0.6, "mrr": 0.5, "map@10": 0.4},
        "lexical": {"ndcg@10": 0.60, "recall@10": 0.7, "mrr": 0.6, "map@10": 0.5},
        "hybrid": {"ndcg@10": 0.70, "recall@10": 0.8, "mrr": 0.7, "map@10": 0.6},
    }
    print_report("scifact", arm_scores)
    out = capsys.readouterr().out
    assert "scifact" in out
    assert "0.665" in out  # published BM25


def test_print_report_flags_lexical_collapse_loudly(capsys):
    """If our lexical arm is far below published BM25, that must be flagged
    loudly -- and the hybrid-collapsing-to-dense interpretation spelled out."""
    arm_scores = {
        "dense": {"ndcg@10": 0.45, "recall@10": 0.5, "mrr": 0.4, "map@10": 0.3},
        "lexical": {"ndcg@10": 0.05, "recall@10": 0.1, "mrr": 0.05, "map@10": 0.02},
        "hybrid": {"ndcg@10": 0.44, "recall@10": 0.5, "mrr": 0.4, "map@10": 0.3},
    }
    print_report("scifact", arm_scores)
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "dense-only" in out


def test_published_baselines_has_both_probe_datasets():
    assert set(PUBLISHED_BASELINES) == {"scifact", "nfcorpus"}
    for dataset, baselines in PUBLISHED_BASELINES.items():
        assert baselines["BM25"] > baselines["DPR"], dataset


# ---------------------------------------------------------------------------
# Validate our RRF against ranx's reference implementation.
# ---------------------------------------------------------------------------


def test_our_rrf_matches_ranx_reference():
    """Our eval.metrics.fuse and ranx's rrf fusion should agree on ORDER for
    the same rankings -- ranx is the reference implementation the rest of
    the field measures against, so if we disagree, that is a real finding,
    not something to fudge away.

    ranx's rrf() computes `1/(k + i + 1)` where `i` is the doc's 0-based
    position in the run once sorted by score descending -- i.e. exactly
    `1/(k + rank)` for a 1-based rank, the same convention eval.metrics.rrf_score
    uses. To feed ranx a *rank* rather than a *score*, we hand it a strictly
    decreasing score (`-rank`) per doc, which sorts back into the same order.
    """
    from ranx import Run
    from ranx import fuse as ranx_fuse

    from eval.metrics import fuse as our_fuse

    dense_ranks = {"A": 1, "B": 2, "C": 3}
    lexical_ranks = {"C": 1, "D": 2}

    dense_run = Run({"q0": {doc: -rank for doc, rank in dense_ranks.items()}})
    lexical_run = Run({"q0": {doc: -rank for doc, rank in lexical_ranks.items()}})

    ranx_result = ranx_fuse(
        runs=[dense_run, lexical_run], method="rrf", params={"k": 60}, norm=None
    )
    ranx_scored = ranx_result.to_dict()["q0"]

    our_scored = dict(our_fuse(dense_ranks, lexical_ranks, k=60))

    # Order agrees: sort both by score descending, tie-break by doc_id for
    # determinism (B and D are a genuine tie at 1/62 in both).
    our_order = sorted(our_scored, key=lambda d: (-our_scored[d], d))
    ranx_order = sorted(ranx_scored, key=lambda d: (-ranx_scored[d], d))
    assert our_order == ranx_order == ["C", "A", "B", "D"]

    # Scores agree too, to floating-point precision -- not just the order.
    for doc_id in our_scored:
        assert our_scored[doc_id] == pytest.approx(float(ranx_scored[doc_id]), rel=1e-9)
