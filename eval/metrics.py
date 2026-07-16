"""Retrieval metrics.

Reciprocal Rank Fusion is per Cormack, Clarke and Buettcher (2009):
a document's score is the sum of 1/(k + rank) across the rankers that found it.
Nothing here is copied from any implementation; it is the formula from the paper.
"""

from __future__ import annotations


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
