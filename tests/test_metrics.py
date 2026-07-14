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
    dense = {"A": 1}
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
