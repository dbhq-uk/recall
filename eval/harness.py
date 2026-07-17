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
    python -m eval.harness              # score at the configured k/weights, limit=10
    python -m eval.harness --sweep      # sweep k and find the best
"""

from __future__ import annotations

import argparse
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from eval.metrics import bootstrap_ci, mrr, paired_bootstrap_delta_ci, recall_at_k
from recall.config import load_config
from recall.embedders import build_embedder
from recall.store.pgvector import PgVectorStore

GOLDEN = Path(__file__).parent / "golden.toml"
SOURCES = ["fixture"]
PRODUCTION_LIMIT = 10  # what a real recall_search(limit=10) call actually returns
CONFIDENCE = 0.95


@dataclass(frozen=True)
class ArmScore:
    recall_at_10: float
    mrr: float
    n: int
    # Per-query scores, in query order, so paired deltas against another arm are
    # computable. Optional and default None so callers that only have the
    # aggregate (e.g. older tests, or a report reconstructed from a printed
    # summary) still work — CI-aware verdicts just degrade to point estimates.
    recall_scores: tuple[float, ...] | None = None
    mrr_scores: tuple[float, ...] | None = None

    def recall_ci(self, confidence: float = CONFIDENCE) -> tuple[float, float] | None:
        if not self.recall_scores:
            return None
        return bootstrap_ci(list(self.recall_scores), confidence=confidence)

    def mrr_ci(self, confidence: float = CONFIDENCE) -> tuple[float, float] | None:
        if not self.mrr_scores:
            return None
        return bootstrap_ci(list(self.mrr_scores), confidence=confidence)


@dataclass
class Report:
    lexical_ranker: str
    k: int
    arms: dict[str, ArmScore]
    by_kind: dict[str, dict[str, ArmScore]]
    limit: int = PRODUCTION_LIMIT

    @staticmethod
    def _arm_verdict(hybrid_score: ArmScore, half_score: ArmScore) -> str:
        """Compare hybrid to one half's ArmScore.

        Returns "win", "loss", "tie" or "noise". "noise" only appears when we
        have per-query scores for both arms and the PAIRED delta-CI (hybrid
        minus half) straddles zero — i.e. the point estimate says one thing but
        the bootstrap says n is too small to trust it. Point estimates alone
        (no per-query scores available) fall back to the old win/loss/tie
        comparison, because there is nothing to bootstrap.
        """
        hybrid = hybrid_score.recall_at_10
        other = half_score.recall_at_10

        if hybrid_score.recall_scores and half_score.recall_scores:
            lo, hi = paired_bootstrap_delta_ci(
                list(hybrid_score.recall_scores), list(half_score.recall_scores)
            )
            if lo > 0.0:
                return "win"
            if hi < 0.0:
                return "loss"
            if hybrid == other:
                return "tie"
            return "noise"

        if hybrid > other:
            return "win"
        if hybrid < other:
            return "loss"
        return "tie"

    def kind_beats_both_halves(self, kind: str) -> bool:
        """Does hybrid beat both dense-only and lexical-only for this one kind?

        "Beat" means a real win: point estimate higher AND (when we have the
        per-query scores to check) the paired delta-CI excludes zero. A kind
        whose apparent win is statistically indistinguishable from noise does
        NOT count — see fusion_is_earning_its_keep for why that matters.
        """
        scores = self.by_kind[kind]
        return self._arm_verdict(scores["hybrid"], scores["dense"]) == "win" and (
            self._arm_verdict(scores["hybrid"], scores["lexical"]) == "win"
        )

    def kind_verdict_text(self, kind: str) -> str:
        """Human-readable verdict for one kind. A tie is honestly reported as a
        tie, a statistically indistinguishable difference is reported as noise
        rather than dressed up as a win, and a genuine loss is reported as a
        loss — not blurred into "noise" just because that sounds softer."""
        scores = self.by_kind[kind]
        dense_v = self._arm_verdict(scores["hybrid"], scores["dense"])
        lexical_v = self._arm_verdict(scores["hybrid"], scores["lexical"])
        n = self.by_kind[kind]["hybrid"].n

        if dense_v == "loss" or lexical_v == "loss":
            return f"LOSES to a half (95% CI excludes 0, n={n})"
        if dense_v == "win" and lexical_v == "win":
            return f"beats both halves (95% CI excludes 0, n={n})"
        if "noise" in (dense_v, lexical_v):
            return f"not distinguishable from noise at n={n} (95% CI includes 0)"
        return f"ties a half (no fusion benefit, n={n})"

    @property
    def losing_kinds(self) -> list[str]:
        """Kinds where hybrid does NOT beat both halves, sorted for stable output."""
        return [kind for kind in sorted(self.by_kind) if not self.kind_beats_both_halves(kind)]

    @property
    def aggregate_wins(self) -> bool:
        """Does hybrid beat both halves on the aggregate numbers alone?

        Uses the same win/loss/tie/noise logic as kind_beats_both_halves: a
        "win" requires the paired delta-CI to exclude zero when per-query
        scores are available, not just a higher point estimate. This is
        necessary but not sufficient: an aggregate can win while hiding a kind
        that loses (see fusion_is_earning_its_keep).
        """
        return self._arm_verdict(self.arms["hybrid"], self.arms["dense"]) == "win" and (
            self._arm_verdict(self.arms["hybrid"], self.arms["lexical"]) == "win"
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


def score(
    k: int | None = None,
    limit: int = PRODUCTION_LIMIT,
    w_dense: float | None = None,
    w_lexical: float | None = None,
) -> Report:
    """Score all three arms against the golden set.

    k/w_dense/w_lexical default to None, which means "whatever RecallConfig
    says" — so the default run (no args) reflects the shipped, honest config,
    and a sweep can still override any of them to explore the space.

    The hybrid arm calls store.search(...) directly — exactly what a
    production recall_search call gets back, weighted fusion included — never
    eval.metrics.fuse() (which stays equal-weight, a pure unit-test helper).
    """
    queries = tomllib.loads(GOLDEN.read_text())["query"]
    config = load_config()
    embedder = build_embedder(config)
    store = PgVectorStore(config.database_url)

    resolved_k = config.rrf_k if k is None else k
    resolved_w_dense = config.fusion_weight_dense if w_dense is None else w_dense
    resolved_w_lexical = config.fusion_weight_lexical if w_lexical is None else w_lexical

    raw: dict[str, list[tuple[str, list[str], set[str]]]] = defaultdict(list)

    for q in queries:
        qvec = embedder.embed_query(q["text"])
        relevant = set(q["relevant"])

        hybrid_result = store.search(
            qvec=qvec,
            qtext=q["text"],
            sources=SOURCES,
            limit=limit,
            k=resolved_k,
            w_dense=resolved_w_dense,
            w_lexical=resolved_w_lexical,
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
        recall_scores = tuple(recall_at_k(r, rel, 10) for _, r, rel in rows)
        mrr_scores = tuple(mrr(r, rel) for _, r, rel in rows)
        return ArmScore(
            recall_at_10=sum(recall_scores) / len(rows),
            mrr=sum(mrr_scores) / len(rows),
            n=len(rows),
            recall_scores=recall_scores,
            mrr_scores=mrr_scores,
        )

    arms = {arm: summarise(rows) for arm, rows in raw.items()}
    kinds = {"semantic", "lexical", "hybrid"}
    by_kind = {
        kind: {arm: summarise([r for r in rows if r[0] == kind]) for arm, rows in raw.items()}
        for kind in kinds
    }

    return Report(
        lexical_ranker=store.lexical_ranker(),
        k=resolved_k,
        arms=arms,
        by_kind=by_kind,
        limit=limit,
    )


def _fmt_ci(ci: tuple[float, float] | None) -> str:
    if ci is None:
        return ""
    lo, hi = ci
    return f" [95% CI {lo:.3f}-{hi:.3f}]"


def _print(report: Report) -> None:
    print(f"\nlexical ranker: {report.lexical_ranker}   RRF k={report.k}   limit={report.limit}\n")
    print(f"{'arm':10} {'n':>4} {'Recall@10':>10} {'MRR':>8}")
    print("-" * 30)
    for arm in ("dense", "lexical", "hybrid"):
        s = report.arms[arm]
        print(
            f"{arm:10} {s.n:>4} {s.recall_at_10:>10.3f}{_fmt_ci(s.recall_ci())} "
            f"{s.mrr:>8.3f}{_fmt_ci(s.mrr_ci())}"
        )

    print(f"\n{'by kind':10} {'arm':10} {'n':>4} {'Recall@10':>10} {'MRR':>8}")
    print("-" * 42)
    for kind in ("semantic", "lexical", "hybrid"):
        for arm in ("dense", "lexical", "hybrid"):
            s = report.by_kind[kind][arm]
            print(
                f"{kind:10} {arm:10} {s.n:>4} {s.recall_at_10:>10.3f}{_fmt_ci(s.recall_ci())} "
                f"{s.mrr:>8.3f}{_fmt_ci(s.mrr_ci())}"
            )
        print(
            f"  verdict [{kind:10}, n={report.by_kind[kind]['hybrid'].n}]: "
            f"hybrid {report.kind_verdict_text(kind)}"
        )
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
            "  Fusion beats both halves, in aggregate and on every kind. RRF is earning its keep."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=None, help="override rrf_k; defaults to config")
    parser.add_argument("--limit", type=int, default=PRODUCTION_LIMIT, help="chunks per arm")
    parser.add_argument("--sweep", action="store_true", help="sweep k and report the best")
    args = parser.parse_args()

    if not args.sweep:
        cfg = load_config()
        print(
            f"fusion weights: w_dense={cfg.fusion_weight_dense}   "
            f"w_lexical={cfg.fusion_weight_lexical}   "
            f"(rrf_k default={cfg.rrf_k}, overridden here: {args.k is not None})"
        )
        _print(score(k=args.k, limit=args.limit))
        return

    print("Sweeping k. 60 is the paper's convention; we ship 10. Neither is a law.\n")
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
    # "Best" here is a bare point estimate over 40 queries, and the sweep is
    # usually flat within noise. This line used to read "if this is far from 60,
    # update the default" — which is how the default silently drifted 60 -> 10 on
    # a difference smaller than one query. A sweep ranks; it does not decide.
    print(
        "\nThis is the best POINT ESTIMATE, not a finding: the sweep does not test\n"
        "whether the winner is distinguishable from the shipped default. Before\n"
        "changing rrf_k, run a paired bootstrap on the two settings\n"
        "(eval.metrics.paired_bootstrap_delta_ci) and record it in the decision\n"
        "log in docs/design.md. A default that moves without a number is a guess."
    )


if __name__ == "__main__":
    main()
