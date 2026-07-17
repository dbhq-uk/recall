"""Retrieval metrics.

Reciprocal Rank Fusion is per Cormack, Clarke and Buettcher (2009):
a document's score is the sum of 1/(k + rank) across the rankers that found it.
Nothing here is copied from any implementation; it is the formula from the paper.
"""

from __future__ import annotations

import random

DEFAULT_SEED = 20260717  # fixed so CI and reruns produce the same interval
DEFAULT_RESAMPLES = 2000


def rrf_score(ranks: list[int | None], k: int = 60) -> float:
    """Sum of 1/(k + rank) over the rankers that found this document.

    A ranker that did not find it contributes nothing (not a penalty).
    """
    return sum(1.0 / (k + r) for r in ranks if r is not None)


def fuse(
    dense_ranks: dict[str, int],
    lexical_ranks: dict[str, int],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Fuse two ranked lists. Returns (doc_id, score) sorted by score, descending.

    Ranks are 1-based. A document present in only one list still scores; a
    document present in both scores the sum, which is why RRF rewards agreement.
    """
    doc_ids = set(dense_ranks) | set(lexical_ranks)
    scored = [
        (doc_id, rrf_score([dense_ranks.get(doc_id), lexical_ranks.get(doc_id)], k=k))
        for doc_id in doc_ids
    ]
    # Sort by score desc, then doc_id asc so ties are deterministic across runs.
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """1.0 if any relevant document appears in the top k, else 0.0.

    This is the hit-rate reading of Recall@k, which is what we want: for these
    queries there is usually one right answer, and what matters is whether the
    agent would have seen it.
    """
    return 1.0 if set(retrieved[:k]) & relevant else 0.0


def mrr(retrieved: list[str], relevant: set[str]) -> float:
    """Reciprocal rank of the first relevant document. 0.0 if there is none."""
    for i, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant:
            return 1.0 / i
    return 0.0


def bootstrap_ci(
    scores: list[float],
    confidence: float = 0.95,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean of per-query scores.

    Resamples `scores` with replacement `n_resamples` times, takes the mean of
    each resample, and returns the (alpha/2, 1-alpha/2) percentiles of that
    resampled-means distribution. Standard nonparametric bootstrap (Efron) —
    no normality assumption, which matters here because Recall@10 is a
    0/1-valued score and its per-query distribution is nothing like Gaussian
    at n=10-15.

    Seeded (default fixed) so a rerun and CI reproduce the identical interval.
    """
    if not scores:
        raise ValueError("bootstrap_ci: scores must not be empty")
    rng = random.Random(seed)
    n = len(scores)
    means = []
    for _ in range(n_resamples):
        resample = [scores[rng.randrange(n)] for _ in range(n)]
        means.append(sum(resample) / n)
    means.sort()
    alpha = 1.0 - confidence
    lo = _percentile(means, alpha / 2)
    hi = _percentile(means, 1.0 - alpha / 2)
    return lo, hi


def paired_bootstrap_delta_ci(
    arm_a: list[float],
    arm_b: list[float],
    confidence: float = 0.95,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> tuple[float, float]:
    """Paired bootstrap CI for the mean delta (arm_a - arm_b) over the SAME queries.

    This is the statistically correct way to ask "is hybrid actually better
    than dense on this golden set?" — it resamples query INDICES (not the two
    score lists independently), so a query's dense score and hybrid score are
    always resampled together. That preserves the pairing: per-query
    differences are what carries the signal, and each query's own noise
    (easy query vs. hard query) mostly cancels rather than adding extra spread
    from two independent resamples.

    IMPORTANT — do not use per-arm bootstrap_ci() intervals to decide whether
    two arms differ. Non-overlapping per-arm CIs *do* imply a significant
    difference, but overlapping per-arm CIs do NOT imply the difference is
    non-significant — comparing two separate intervals by eye is a classic
    statistical fallacy because it ignores the (usually positive) covariance
    between paired observations. The only correct test of "does hybrid beat a
    half" is: does THIS function's delta CI exclude zero? Do not "simplify"
    the verdict logic back to eyeballing overlap.
    """
    if len(arm_a) != len(arm_b):
        raise ValueError("paired_bootstrap_delta_ci: arm_a and arm_b must be the same length")
    if not arm_a:
        raise ValueError("paired_bootstrap_delta_ci: arms must not be empty")
    rng = random.Random(seed)
    n = len(arm_a)
    deltas = []
    for _ in range(n_resamples):
        idxs = [rng.randrange(n) for _ in range(n)]
        resampled_delta = sum(arm_a[i] - arm_b[i] for i in idxs) / n
        deltas.append(resampled_delta)
    deltas.sort()
    alpha = 1.0 - confidence
    lo = _percentile(deltas, alpha / 2)
    hi = _percentile(deltas, 1.0 - alpha / 2)
    return lo, hi


def _percentile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolation percentile of an already-sorted list, p in [0, 1]."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = p * (len(sorted_values) - 1)
    lower = int(idx)
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = idx - lower
    return sorted_values[lower] + frac * (sorted_values[upper] - sorted_values[lower])
