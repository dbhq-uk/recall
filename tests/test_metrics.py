import pytest

from eval.metrics import bootstrap_ci, fuse, mrr, paired_bootstrap_delta_ci, recall_at_k, rrf_score


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


def test_bootstrap_ci_of_constant_scores_is_a_point():
    """All scores identical: resampling can't produce any spread."""
    lo, hi = bootstrap_ci([1.0] * 20, seed=1)
    assert lo == pytest.approx(1.0)
    assert hi == pytest.approx(1.0)


def test_bootstrap_ci_brackets_the_mean():
    scores = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0]
    lo, hi = bootstrap_ci(scores, seed=1)
    mean = sum(scores) / len(scores)
    assert lo <= mean <= hi
    assert 0.0 <= lo <= hi <= 1.0


def test_bootstrap_ci_is_deterministic_given_a_seed():
    scores = [1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0]
    a = bootstrap_ci(scores, seed=7)
    b = bootstrap_ci(scores, seed=7)
    assert a == b


def test_bootstrap_ci_different_seeds_can_differ():
    """Not a hard requirement of correctness, but confirms the seed is actually wired
    into the RNG rather than ignored."""
    scores = [0.1, 0.37, 0.62, 0.05, 0.88, 0.44, 0.21, 0.73, 0.5, 0.19]
    a = bootstrap_ci(scores, seed=1)
    b = bootstrap_ci(scores, seed=2)
    assert a != b


def test_bootstrap_ci_rejects_empty_scores():
    with pytest.raises(ValueError):
        bootstrap_ci([], seed=1)


def test_paired_bootstrap_delta_ci_requires_matching_lengths():
    with pytest.raises(ValueError):
        paired_bootstrap_delta_ci([1.0, 0.0], [1.0], seed=1)


def test_paired_bootstrap_delta_ci_of_identical_arms_is_zero():
    """Same scores on both arms, in the same order: every resampled delta is 0."""
    a = [1.0, 0.0, 1.0, 1.0, 0.0]
    lo, hi = paired_bootstrap_delta_ci(a, a, seed=1)
    assert lo == pytest.approx(0.0)
    assert hi == pytest.approx(0.0)


def test_paired_bootstrap_delta_ci_excludes_zero_for_a_clear_win():
    """Hybrid beats dense on every single query: the delta CI should exclude zero,
    which is the ONLY thing that should ever be used to call a win significant."""
    hybrid = [1.0] * 20
    dense = [0.0] * 20
    lo, hi = paired_bootstrap_delta_ci(hybrid, dense, seed=1)
    assert lo > 0.0
    assert hi > 0.0


def test_paired_bootstrap_delta_ci_includes_zero_when_indistinguishable():
    """Small n, mixed signal: the delta CI should straddle zero, i.e. genuinely
    inconclusive, not a false win or false loss."""
    hybrid = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
    dense = [0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0]
    lo, hi = paired_bootstrap_delta_ci(hybrid, dense, seed=1)
    assert lo < 0.0 < hi


def test_paired_bootstrap_delta_ci_is_deterministic_given_a_seed():
    hybrid = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0]
    dense = [0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0]
    a = paired_bootstrap_delta_ci(hybrid, dense, seed=3)
    b = paired_bootstrap_delta_ci(hybrid, dense, seed=3)
    assert a == b


def test_paired_bootstrap_delta_ci_rejects_empty_input():
    with pytest.raises(ValueError):
        paired_bootstrap_delta_ci([], [], seed=1)


# --- Interval-aware verdicts in the harness ---------------------------------


def test_armscore_without_per_query_scores_keeps_old_point_estimate_verdict():
    """Back-compat: a Report built the old way (no recall_scores) still gets a
    point-estimate verdict, so callers/tests that predate this task don't break."""
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
    assert r.fusion_is_earning_its_keep is True


def test_kind_verdict_is_a_real_win_when_delta_ci_excludes_zero():
    from eval.harness import ArmScore, Report

    hybrid_scores = [1.0] * 15
    dense_scores = [0.0] * 15
    lexical_scores = [0.0] * 15

    def s(scores: list[float]) -> ArmScore:
        return ArmScore(
            recall_at_10=sum(scores) / len(scores),
            mrr=sum(scores) / len(scores),
            n=len(scores),
            recall_scores=tuple(scores),
            mrr_scores=tuple(scores),
        )

    r = Report(
        lexical_ranker="bm25",
        k=60,
        limit=10,
        arms={"dense": s(dense_scores), "lexical": s(lexical_scores), "hybrid": s(hybrid_scores)},
        by_kind={
            "semantic": {
                "dense": s(dense_scores),
                "lexical": s(lexical_scores),
                "hybrid": s(hybrid_scores),
            }
        },
    )
    assert "beats both halves" in r.kind_verdict_text("semantic")
    assert r.kind_beats_both_halves("semantic") is True


def test_kind_verdict_says_noise_when_point_estimate_differs_but_ci_includes_zero():
    """This is the core of the task: a small-n point-estimate win must NOT be
    reported as a win if the paired delta CI straddles zero."""
    from eval.harness import ArmScore, Report

    # Mixed, noisy signal at small n: hybrid nominally higher than dense but not
    # by a margin the bootstrap can call real.
    hybrid_scores = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0]
    dense_scores = [0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0]
    lexical_scores = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0]

    def s(scores: list[float]) -> ArmScore:
        return ArmScore(
            recall_at_10=sum(scores) / len(scores),
            mrr=sum(scores) / len(scores),
            n=len(scores),
            recall_scores=tuple(scores),
            mrr_scores=tuple(scores),
        )

    r = Report(
        lexical_ranker="bm25",
        k=60,
        limit=10,
        arms={"dense": s(dense_scores), "lexical": s(lexical_scores), "hybrid": s(hybrid_scores)},
        by_kind={
            "semantic": {
                "dense": s(dense_scores),
                "lexical": s(lexical_scores),
                "hybrid": s(hybrid_scores),
            }
        },
    )
    text = r.kind_verdict_text("semantic")
    assert "noise" in text.lower()
    assert "beats both halves" not in text
    # Must not claim the fusion is earning its keep on a noisy, indistinguishable kind.
    assert r.kind_beats_both_halves("semantic") is False


def test_kind_verdict_is_a_genuine_loss_when_delta_ci_excludes_zero_below():
    from eval.harness import ArmScore, Report

    hybrid_scores = [0.0] * 15
    dense_scores = [1.0] * 15
    lexical_scores = [1.0] * 15

    def s(scores: list[float]) -> ArmScore:
        return ArmScore(
            recall_at_10=sum(scores) / len(scores),
            mrr=sum(scores) / len(scores),
            n=len(scores),
            recall_scores=tuple(scores),
            mrr_scores=tuple(scores),
        )

    r = Report(
        lexical_ranker="bm25",
        k=60,
        limit=10,
        arms={"dense": s(dense_scores), "lexical": s(lexical_scores), "hybrid": s(hybrid_scores)},
        by_kind={
            "semantic": {
                "dense": s(dense_scores),
                "lexical": s(lexical_scores),
                "hybrid": s(hybrid_scores),
            }
        },
    )
    assert "LOSES" in r.kind_verdict_text("semantic")


def test_print_includes_confidence_intervals_and_sample_size(capsys):
    from eval.harness import ArmScore, Report, _print

    hybrid_scores = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0]
    dense_scores = [0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    lexical_scores = [1.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0]

    def s(scores: list[float]) -> ArmScore:
        return ArmScore(
            recall_at_10=sum(scores) / len(scores),
            mrr=sum(scores) / len(scores),
            n=len(scores),
            recall_scores=tuple(scores),
            mrr_scores=tuple(scores),
        )

    r = Report(
        lexical_ranker="bm25",
        k=60,
        limit=10,
        arms={"dense": s(dense_scores), "lexical": s(lexical_scores), "hybrid": s(hybrid_scores)},
        by_kind={
            "semantic": {
                "dense": s(dense_scores),
                "lexical": s(lexical_scores),
                "hybrid": s(hybrid_scores),
            },
            "lexical": {
                "dense": s(dense_scores),
                "lexical": s(lexical_scores),
                "hybrid": s(hybrid_scores),
            },
            "hybrid": {
                "dense": s(dense_scores),
                "lexical": s(lexical_scores),
                "hybrid": s(hybrid_scores),
            },
        },
    )
    _print(r)
    out = capsys.readouterr().out
    assert "n=10" in out
    assert "95% CI" in out or "CI" in out
