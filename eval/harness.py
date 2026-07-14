"""The golden-query harness.

Golden queries are the only number that matters. Public code-retrieval benchmarks
are contaminated — their queries are often derived from the target text verbatim —
and they will flatter us. This does not.

Each arm serves its own true top-`limit` CHUNKS, exactly as a real system would:
- dense-only:   the true top-limit by cosine distance (search_dense_only).
- lexical-only: the true top-limit by the live lexical ranker (search_lexical_only).
- hybrid:       exactly what a production `recall_search` call gets back —
                store.search(..., limit=limit, k=k), RRF over the production pool.

Baselines are NOT derived by re-sorting the fused hybrid result: that biases
them, because the fused result only contains docs that survived fusion in the
first place. Each arm queries the database independently, at the same limit a
real agent would use (10, by default) — not some oversized pool that hands
rank-credit to hundreds of chunks no agent would ever see.

Run:
    python -m eval.harness              # score at k=60, limit=10
    python -m eval.harness --sweep      # sweep k and find the best
"""

from __future__ import annotations

import argparse
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from eval.metrics import mrr, recall_at_k
from recall.config import load_config
from recall.embedders import build_embedder
from recall.store.pgvector import PgVectorStore

GOLDEN = Path(__file__).parent / "golden.toml"
SOURCES = ["fixture"]
PRODUCTION_LIMIT = 10  # what a real recall_search(limit=10) call actually returns


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
    limit: int = PRODUCTION_LIMIT

    def kind_beats_both_halves(self, kind: str) -> bool:
        """Does hybrid beat both dense-only and lexical-only for this one kind?"""
        scores = self.by_kind[kind]
        hybrid = scores["hybrid"].recall_at_10
        return hybrid > scores["dense"].recall_at_10 and hybrid > scores["lexical"].recall_at_10

    def kind_verdict_text(self, kind: str) -> str:
        """Human-readable verdict for one kind. A tie is honestly reported as a
        tie, not dressed up as a win or overstated as a loss."""
        scores = self.by_kind[kind]
        hybrid = scores["hybrid"].recall_at_10
        dense = scores["dense"].recall_at_10
        lexical = scores["lexical"].recall_at_10
        if hybrid > dense and hybrid > lexical:
            return "beats both halves"
        if hybrid < dense or hybrid < lexical:
            return "LOSES to a half"
        return "ties a half (no fusion benefit)"

    @property
    def losing_kinds(self) -> list[str]:
        """Kinds where hybrid does NOT beat both halves, sorted for stable output."""
        return [kind for kind in sorted(self.by_kind) if not self.kind_beats_both_halves(kind)]

    @property
    def aggregate_wins(self) -> bool:
        """Does hybrid beat both halves on the aggregate numbers alone?

        This is necessary but not sufficient: an aggregate can win while hiding
        a kind that loses (see fusion_is_earning_its_keep).
        """
        hybrid = self.arms["hybrid"].recall_at_10
        return (
            hybrid > self.arms["dense"].recall_at_10
            and hybrid > self.arms["lexical"].recall_at_10
        )

    @property
    def fusion_is_earning_its_keep(self) -> bool:
        """Does hybrid actually beat BOTH halves — in aggregate AND on every kind?

        A winning aggregate can hide a losing kind: that is exactly the sin
        CLAUDE.md forbids ("honest failure" — no silent fallbacks, no declaring
        success while degraded). If RRF fuses nothing for one kind of query, we
        say so, even while the aggregate looks fine.
        """
        return self.aggregate_wins and not self.losing_kinds


def score(k: int = 60, limit: int = PRODUCTION_LIMIT) -> Report:
    queries = tomllib.loads(GOLDEN.read_text())["query"]
    config = load_config()
    embedder = build_embedder(config)
    store = PgVectorStore(config.database_url)

    raw: dict[str, list[tuple[str, list[str], set[str]]]] = defaultdict(list)

    for q in queries:
        qvec = embedder.embed_query(q["text"])
        relevant = set(q["relevant"])

        hybrid_result = store.search(
            qvec=qvec, qtext=q["text"], sources=SOURCES, limit=limit, k=k
        )
        rankings = {
            "dense": store.search_dense_only(qvec=qvec, sources=SOURCES, limit=limit),
            "lexical": store.search_lexical_only(qtext=q["text"], sources=SOURCES, limit=limit),
            "hybrid": [h.rel_path for h in hybrid_result.hits],
        }
        for arm, ranking in rankings.items():
            raw[arm].append((q["kind"], ranking, relevant))

    def summarise(rows: list[tuple[str, list[str], set[str]]]) -> ArmScore:
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

    return Report(
        lexical_ranker=store.lexical_ranker(), k=k, arms=arms, by_kind=by_kind, limit=limit
    )


def _print(report: Report) -> None:
    print(f"\nlexical ranker: {report.lexical_ranker}   RRF k={report.k}   limit={report.limit}\n")
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
        print(f"  verdict [{kind:10}]: hybrid {report.kind_verdict_text(kind)}")
        print()

    print("overall verdict:")
    if not report.aggregate_wins:
        print(
            "  WARNING: hybrid does NOT beat both halves.\n"
            "  RRF is not paying for itself on this corpus. Do not ship this quietly —\n"
            "  tune k, or try convex combination, or say so in the README."
        )
    elif report.losing_kinds:
        print(
            "  WARNING: hybrid wins in aggregate but LOSES to a half on: "
            f"{', '.join(report.losing_kinds)}.\n"
            "  A winning aggregate hides a per-kind failure — this is NOT\n"
            '  "RRF is earning its keep". Investigate the losing kind before shipping.'
        )
    else:
        print(
            "  Fusion beats both halves, in aggregate and on every kind. "
            "RRF is earning its keep."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=60)
    parser.add_argument("--limit", type=int, default=PRODUCTION_LIMIT, help="chunks per arm")
    parser.add_argument("--sweep", action="store_true", help="sweep k and report the best")
    args = parser.parse_args()

    if not args.sweep:
        _print(score(k=args.k, limit=args.limit))
        return

    print("Sweeping k. k=60 is a convention, not a law.\n")
    print(f"{'k':>6} {'hybrid R@10':>12} {'hybrid MRR':>12}")
    print("-" * 32)
    best = None
    for k in (1, 5, 10, 20, 40, 60, 80, 120, 200):
        r = score(k=k, limit=args.limit)
        h = r.arms["hybrid"]
        print(f"{k:>6} {h.recall_at_10:>12.3f} {h.mrr:>12.3f}")
        if best is None or h.mrr > best[1]:
            best = (k, h.mrr)
    print(f"\nBest k by MRR: {best[0]} (MRR {best[1]:.3f})")
    print("If this is far from 60, update the default in RecallConfig and say why.")


if __name__ == "__main__":
    main()
