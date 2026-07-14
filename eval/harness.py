"""The golden-query harness.

Golden queries are the only number that matters. Public code-retrieval benchmarks
are contaminated — their queries are often derived from the target text verbatim —
and they will flatter us. This does not.

Run:
    python -m eval.harness              # score at k=60
    python -m eval.harness --sweep      # sweep k and find the best
"""

from __future__ import annotations

import argparse
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from eval.metrics import fuse, mrr, recall_at_k
from recall.config import load_config
from recall.embedders import build_embedder
from recall.store.pgvector import PgVectorStore

GOLDEN = Path(__file__).parent / "golden.toml"
POOL_LIMIT = 200  # big enough that the top-10 of every arm is inside it


@dataclass(frozen=True)
class ArmScore:
    recall_at_10: float
    mrr: float
    n: int


@dataclass
class Report:
    lexical_ranker: str
    k: int
    arms: dict[str, ArmScore]
    by_kind: dict[str, dict[str, ArmScore]]

    @property
    def fusion_is_earning_its_keep(self) -> bool:
        """Does hybrid actually beat BOTH halves? If not, RRF is not paying for
        itself, and we say so rather than shipping a fusion that fuses nothing."""
        hybrid = self.arms["hybrid"].recall_at_10
        return (
            hybrid > self.arms["dense"].recall_at_10
            and hybrid > self.arms["lexical"].recall_at_10
        )


def _rankings(hits, k: int) -> dict[str, list[str]]:
    """Derive all three rankings from one pool. Every hit already carries its
    dense_rank and lexical_rank, and RRF is a pure function of ranks."""
    dense = {h.rel_path: h.dense_rank for h in hits if h.dense_rank is not None}
    lexical = {h.rel_path: h.lexical_rank for h in hits if h.lexical_rank is not None}

    return {
        "dense": [p for p, _ in sorted(dense.items(), key=lambda kv: kv[1])],
        "lexical": [p for p, _ in sorted(lexical.items(), key=lambda kv: kv[1])],
        "hybrid": [doc for doc, _ in fuse(dense, lexical, k=k)],
    }


def score(k: int = 60) -> Report:
    queries = tomllib.loads(GOLDEN.read_text())["query"]
    config = load_config()
    embedder = build_embedder(config)
    store = PgVectorStore(config.database_url)

    raw: dict[str, list[tuple[str, list[str], set[str]]]] = defaultdict(list)

    for q in queries:
        qvec = embedder.embed_query(q["text"])
        result = store.search(
            qvec=qvec, qtext=q["text"], sources=["fixture"], limit=POOL_LIMIT, k=k
        )
        relevant = set(q["relevant"])
        for arm, ranking in _rankings(result.hits, k=k).items():
            raw[arm].append((q["kind"], ranking, relevant))

    def summarise(rows) -> ArmScore:
        if not rows:
            return ArmScore(0.0, 0.0, 0)
        return ArmScore(
            recall_at_10=sum(recall_at_k(r, rel, 10) for _, r, rel in rows) / len(rows),
            mrr=sum(mrr(r, rel) for _, r, rel in rows) / len(rows),
            n=len(rows),
        )

    arms = {arm: summarise(rows) for arm, rows in raw.items()}
    kinds = {"semantic", "lexical", "hybrid"}
    by_kind = {
        kind: {arm: summarise([r for r in rows if r[0] == kind]) for arm, rows in raw.items()}
        for kind in kinds
    }

    return Report(lexical_ranker=store.lexical_ranker(), k=k, arms=arms, by_kind=by_kind)


def _print(report: Report) -> None:
    print(f"\nlexical ranker: {report.lexical_ranker}   RRF k={report.k}\n")
    print(f"{'arm':10} {'Recall@10':>10} {'MRR':>8}")
    print("-" * 30)
    for arm in ("dense", "lexical", "hybrid"):
        s = report.arms[arm]
        print(f"{arm:10} {s.recall_at_10:>10.3f} {s.mrr:>8.3f}")

    print(f"\n{'by kind':10} {'arm':10} {'Recall@10':>10} {'MRR':>8}")
    print("-" * 42)
    for kind in ("semantic", "lexical", "hybrid"):
        for arm in ("dense", "lexical", "hybrid"):
            s = report.by_kind[kind][arm]
            print(f"{kind:10} {arm:10} {s.recall_at_10:>10.3f} {s.mrr:>8.3f}")
        print()

    if report.fusion_is_earning_its_keep:
        print("Fusion beats both halves. RRF is earning its keep.")
    else:
        print(
            "WARNING: hybrid does NOT beat both halves.\n"
            "RRF is not paying for itself on this corpus. Do not ship this quietly —\n"
            "tune k, or try convex combination, or say so in the README."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=60)
    parser.add_argument("--sweep", action="store_true", help="sweep k and report the best")
    args = parser.parse_args()

    if not args.sweep:
        _print(score(k=args.k))
        return

    print("Sweeping k. k=60 is a convention, not a law.\n")
    print(f"{'k':>6} {'hybrid R@10':>12} {'hybrid MRR':>12}")
    print("-" * 32)
    best = None
    for k in (1, 5, 10, 20, 40, 60, 80, 120, 200):
        r = score(k=k)
        h = r.arms["hybrid"]
        print(f"{k:>6} {h.recall_at_10:>12.3f} {h.mrr:>12.3f}")
        if best is None or h.mrr > best[1]:
            best = (k, h.mrr)
    print(f"\nBest k by MRR: {best[0]} (MRR {best[1]:.3f})")
    print("If this is far from 60, update the default in RecallConfig and say why.")


if __name__ == "__main__":
    main()
