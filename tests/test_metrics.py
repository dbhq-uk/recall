import pytest

from eval.metrics import fuse, mrr, recall_at_k, rrf_score


def test_rrf_score_matches_the_paper():
    """Cormack, Clarke & Buettcher (2009): score = sum of 1/(k + rank)."""
    assert rrf_score([1], k=60) == pytest.approx(1 / 61)
    assert rrf_score([1, 1], k=60) == pytest.approx(2 / 61)
    assert rrf_score([None], k=60) == 0.0


def test_rrf_hand_worked_example_verified_against_live_postgres():
    """This exact example was run against the real database during planning.

    dense:   A=1, B=2, C=3
    lexical: C=1, D=2
    k = 60

    C = 1/63 + 1/61 = 0.032266458...   <- the only doc both halves found
    A = 1/61        = 0.016393442...
    B = 1/62        = 0.016129032...
    D = 1/62        = 0.016129032...

    Postgres returned 0.03226645849596669269 for C. So must we.
    """
    dense = {"A": 1, "B": 2, "C": 3}
    lexical = {"C": 1, "D": 2}
    ranked = fuse(dense, lexical, k=60)

    assert ranked[0][0] == "C"
    assert ranked[0][1] == pytest.approx(0.03226645849596669, rel=1e-12)
    assert ranked[1][0] == "A"
    assert ranked[1][1] == pytest.approx(1 / 61)
    # B and D tie exactly at 1/62.
    assert {ranked[2][0], ranked[3][0]} == {"B", "D"}
    assert ranked[2][1] == pytest.approx(1 / 62)
    assert ranked[3][1] == pytest.approx(1 / 62)


def test_fuse_rewards_agreement_between_the_halves():
    """The core claim of RRF: a doc both halves like beats a doc only one half loves."""
    # D is rank 1 in dense but invisible to lexical.
    # C is only rank 3 and 3, but BOTH halves found it.
    dense = {"D": 1, "C": 3}
    lexical = {"X": 1, "C": 3}
    ranked = dict(fuse(dense, lexical, k=60))
    assert ranked["C"] > ranked["D"]


def test_smaller_k_sharpens_the_top_of_the_ranking():
    """k is a knob, not a law. The design says the golden set should decide it."""
    assert rrf_score([1], k=1) > rrf_score([1], k=60)


def test_recall_at_k_is_a_hit_or_miss():
    assert recall_at_k(["a", "b", "c"], {"c"}, k=10) == 1.0
    assert recall_at_k(["a", "b", "c"], {"z"}, k=10) == 0.0


def test_recall_at_k_respects_the_cutoff():
    assert recall_at_k(["a", "b", "c"], {"c"}, k=2) == 0.0
    assert recall_at_k(["a", "b", "c"], {"c"}, k=3) == 1.0


def test_mrr_uses_the_first_relevant_hit():
    assert mrr(["a", "b", "c"], {"b"}) == pytest.approx(1 / 2)
    assert mrr(["a", "b", "c"], {"a"}) == pytest.approx(1.0)
    assert mrr(["a", "b", "c"], {"c"}) == pytest.approx(1 / 3)


def test_mrr_of_a_total_miss_is_zero():
    assert mrr(["a", "b"], {"z"}) == 0.0


def test_mrr_takes_the_best_when_several_are_relevant():
    assert mrr(["a", "b", "c"], {"b", "c"}) == pytest.approx(1 / 2)


def test_harness_report_shape():
    """The harness must always report all three arms, or a reader could mistake a
    dense-only number for a hybrid one."""
    from eval.harness import ArmScore, Report

    r = Report(
        lexical_ranker="bm25",
        k=60,
        limit=10,
        arms={
            "dense": ArmScore(recall_at_10=0.5, mrr=0.4, n=40),
            "lexical": ArmScore(recall_at_10=0.6, mrr=0.5, n=40),
            "hybrid": ArmScore(recall_at_10=0.8, mrr=0.7, n=40),
        },
        by_kind={},
    )
    assert set(r.arms) == {"dense", "lexical", "hybrid"}
    assert r.fusion_is_earning_its_keep is True


def test_harness_says_so_when_fusion_is_NOT_earning_its_keep():
    from eval.harness import ArmScore, Report

    r = Report(
        lexical_ranker="bm25",
        k=60,
        limit=10,
        arms={
            "dense": ArmScore(recall_at_10=0.9, mrr=0.8, n=40),
            "lexical": ArmScore(recall_at_10=0.6, mrr=0.5, n=40),
            "hybrid": ArmScore(recall_at_10=0.85, mrr=0.7, n=40),  # worse than dense alone
        },
        by_kind={},
    )
    assert r.fusion_is_earning_its_keep is False


def test_harness_does_NOT_declare_victory_when_a_kind_is_losing_under_a_winning_aggregate():
    """Pin the exact bug this task fixes: a winning aggregate can hide a kind
    that hybrid actually loses on. The verdict — and the printed summary — must
    surface that, rather than a blanket 'RRF is earning its keep'."""
    from eval.harness import ArmScore, Report

    def s(recall: float, m: float) -> ArmScore:
        return ArmScore(recall_at_10=recall, mrr=m, n=10)

    r = Report(
        lexical_ranker="bm25",
        k=60,
        limit=10,
        arms={
            "dense": s(0.80, 0.70),
            "lexical": s(0.70, 0.60),
            "hybrid": s(0.85, 0.75),  # aggregate: hybrid beats BOTH halves
        },
        by_kind={
            "semantic": {
                "dense": s(0.95, 0.86),
                "lexical": s(0.50, 0.40),
                "hybrid": s(0.90, 0.80),  # hybrid LOSES to dense-only here
            },
            "lexical": {
                "dense": s(0.60, 0.50),
                "lexical": s(0.90, 0.80),
                "hybrid": s(0.95, 0.85),
            },
            "hybrid": {
                "dense": s(0.80, 0.70),
                "lexical": s(0.70, 0.60),
                "hybrid": s(0.90, 0.80),
            },
        },
    )

    assert r.aggregate_wins is True
    assert r.kind_beats_both_halves("semantic") is False
    assert r.losing_kinds == ["semantic"]
    # The aggregate alone says "ship it". The honest verdict must not.
    assert r.fusion_is_earning_its_keep is False


def test_print_names_the_losing_kind_instead_of_a_blanket_verdict(capsys):
    """The printed summary is what a human actually reads. It must name the
    losing kind, and must NOT print the "RRF is earning its keep" line while a
    kind is degraded."""
    from eval.harness import ArmScore, Report, _print

    def s(recall: float, m: float) -> ArmScore:
        return ArmScore(recall_at_10=recall, mrr=m, n=10)

    r = Report(
        lexical_ranker="bm25",
        k=60,
        limit=10,
        arms={
            "dense": s(0.80, 0.70),
            "lexical": s(0.70, 0.60),
            "hybrid": s(0.85, 0.75),
        },
        by_kind={
            "semantic": {
                "dense": s(0.95, 0.86),
                "lexical": s(0.50, 0.40),
                "hybrid": s(0.90, 0.80),
            },
            "lexical": {
                "dense": s(0.60, 0.50),
                "lexical": s(0.90, 0.80),
                "hybrid": s(0.95, 0.85),
            },
            "hybrid": {
                "dense": s(0.80, 0.70),
                "lexical": s(0.70, 0.60),
                "hybrid": s(0.90, 0.80),
            },
        },
    )

    _print(r)
    out = capsys.readouterr().out

    assert "semantic" in out
    assert "Fusion beats both halves, in aggregate and on every kind" not in out
