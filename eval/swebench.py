"""The SWE-bench retrieval-precision harness.

The golden set in eval/golden.toml is ours: we wrote the queries and we wrote
the relevance labels, so however careful we are, it can flatter us. This
harness is the un-authored counterpart. For each SWE-bench_Verified instance
we did not write the query (the issue's problem_statement) and we did not
write the relevance labels (the files the accepted, human-written patch
actually touched). It complements the golden set; it does not replace it.

For each instance:
    query    = problem_statement
    corpus   = the instance's own repo, checked out at base_commit
    relevant = the files gold_files_from_patch() extracts from the patch

We score three arms exactly as eval/harness.py does: dense-only, lexical-only
and hybrid, each queried independently at the same limit a real agent would
use, never derived by re-sorting the fused pool.

Two speeds live in this one module:
  - Fast, pure, unit-tested: gold_files_from_patch, file_metrics,
    chunks_to_ranked_files, fetch_instances (network-only, no clone/index),
    aggregate, print_report. These are exercised by tests/test_swebench.py
    with no network, no git and no database.
  - Slow, real, __main__-only: prepare_repo (clones+checks out a real repo)
    and the main() driver (clones, indexes, scores, then deletes the tag for
    every instance). Real indexing runs ~35 minutes per repo on a CPU-only
    box, so this path is never exercised by the test suite -- a controller
    drives it deliberately, outside the fast iteration loop.

Run (slow, real):
    python -m eval.swebench --repos psf/requests --limit 5 --k 10
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import tomli_w

from eval.metrics import mrr
from recall.config import RecallConfig, Registry, load_config
from recall.embedders import Embedder, build_embedder
from recall.indexer import index_source
from recall.store.pgvector import PgVectorStore

HF_ROWS_URL = "https://datasets-server.huggingface.co/rows"
DATASET = "princeton-nlp/SWE-bench_Verified"
SPLIT = "test"
CONFIG_NAME = "default"
PAGE_SIZE = 100
TOTAL_ROWS = 500  # SWE-bench_Verified is exactly 500 instances.

# Small, CPU-tractable repos. Django and the like are too big to index on a
# CPU-only box in reasonable time -- see the module docstring on speeds.
DEFAULT_REPOS = ["psf/requests", "pallets/flask", "pytest-dev/pytest", "mwaskom/seaborn"]
DEFAULT_K = 10

_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SweInstance:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    gold_files: list[str]
    difficulty: str


class _HasRelPath(Protocol):
    rel_path: str


# ---------------------------------------------------------------------------
# Pure functions -- these are what tests/test_swebench.py exercises directly.
# ---------------------------------------------------------------------------


def gold_files_from_patch(patch: str) -> list[str]:
    """Ground truth: the files the accepted patch actually modified.

    Parses `diff --git a/<path> b/<path>` header lines and returns the `b/`
    path with its prefix stripped, in first-seen order, deduplicated. The
    `b/` path is correct for every shape git produces: an ordinary edit has
    a == b; an added file has `--- /dev/null` but its header still carries
    both a/ and b/ as the same path; a deleted file is symmetric; a rename
    or copy has a != b, and `b/` is the file's path after the patch, which is
    what a search over the post-patch tree should have found.
    """
    files: list[str] = []
    seen: set[str] = set()
    for line in patch.splitlines():
        match = _DIFF_HEADER_RE.match(line)
        if not match:
            continue
        b_path = match.group(2)
        if b_path not in seen:
            seen.add(b_path)
            files.append(b_path)
    return files


def _dedup_preserve_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def chunks_to_ranked_files(hits: Iterable[_HasRelPath]) -> list[str]:
    """Collapse ranked chunk hits to unique rel_paths in rank order.

    A file may be reached via several of its own chunks; only its first
    (best-ranked) occurrence should count towards file-level metrics.
    """
    return _dedup_preserve_order(hit.rel_path for hit in hits)


def file_metrics(ranked_files: list[str], gold: set[str], k: int) -> dict[str, float]:
    """File-level recall/precision/F1 at k, plus MRR over the full ranking.

    recall_at_k    = |gold intersect top_k| / |gold|            (0.0 if gold is empty)
    precision_at_k = |gold intersect top_k| / len(top_k)         (0.0 if top_k is empty;
                                                                    this is /k when there
                                                                    are at least k results,
                                                                    /len(top_k) when there
                                                                    are fewer)
    f1_at_k        = harmonic mean of the two above (0.0 if both are 0.0)
    mrr            = reciprocal rank of the first gold file anywhere in
                     ranked_files (not just the top k) -- reused from
                     eval.metrics.mrr, which is exactly this definition.
    """
    top_k = ranked_files[:k]
    hit_count = len(gold & set(top_k))
    recall = hit_count / len(gold) if gold else 0.0
    precision = hit_count / len(top_k) if top_k else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {
        "recall_at_k": recall,
        "precision_at_k": precision,
        "f1_at_k": f1,
        "mrr": mrr(ranked_files, gold),
    }


# ---------------------------------------------------------------------------
# Dataset fetching -- network, but not clone/index, so it stays fast enough
# to unit-test with an injected _rows_fetcher and to smoke-test for real.
# ---------------------------------------------------------------------------

RowsFetcher = Callable[[int, int], list[dict[str, Any]]]


def _fetch_rows_page(offset: int, length: int) -> list[dict[str, Any]]:
    """One page of the HuggingFace datasets-server rows API, flattened.

    The API wraps each row as {"row_idx": .., "row": {...columns...},
    "truncated_cells": [...]}; callers just want the column dicts.
    """
    response = httpx.get(
        HF_ROWS_URL,
        params={
            "dataset": DATASET,
            "config": CONFIG_NAME,
            "split": SPLIT,
            "offset": offset,
            "length": length,
        },
        timeout=60.0,
    )
    response.raise_for_status()
    payload = response.json()
    return [item["row"] for item in payload.get("rows", [])]


def fetch_instances(
    repos: list[str] | None = None,
    limit: int | None = None,
    _rows_fetcher: RowsFetcher | None = None,
) -> list[SweInstance]:
    """Fetch SWE-bench_Verified instances, filtered to `repos` and capped at `limit`.

    Paginates the datasets-server rows API 100 rows at a time, up to the
    dataset's 500 total. `repos` defaults to DEFAULT_REPOS -- small repos
    that are CPU-tractable to index; Django-sized repos are out of scope.

    `_rows_fetcher(offset, length) -> list[row dict]` lets tests substitute a
    synthetic page source so this is unit-testable with no network access.
    A page shorter than `length` is treated as the last page.
    """
    fetcher = _rows_fetcher or _fetch_rows_page
    wanted = set(repos) if repos is not None else set(DEFAULT_REPOS)

    instances: list[SweInstance] = []
    offset = 0
    while offset < TOTAL_ROWS:
        if limit is not None and len(instances) >= limit:
            break
        page = fetcher(offset, PAGE_SIZE)
        if not page:
            break
        for row in page:
            if row["repo"] not in wanted:
                continue
            instances.append(
                SweInstance(
                    instance_id=row["instance_id"],
                    repo=row["repo"],
                    base_commit=row["base_commit"],
                    problem_statement=row["problem_statement"],
                    gold_files=gold_files_from_patch(row["patch"]),
                    difficulty=row["difficulty"],
                )
            )
            if limit is not None and len(instances) >= limit:
                break
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return instances


# ---------------------------------------------------------------------------
# The runner. prepare_repo does real git; evaluate_instance assumes the repo
# is already indexed and only ever reads from the store. Neither is exercised
# by the unit tests -- evaluate_instance needs a live store/embedder,
# prepare_repo needs a live network and git.
# ---------------------------------------------------------------------------


def prepare_repo(instance: SweInstance, work_dir: Path) -> Path:
    """Shallow (blob:none) clone `instance.repo` at `instance.base_commit`.

    Clones into `work_dir/<instance_id>`, checks out base_commit, and writes
    a `.recall.toml` tagging the source `swe-<instance_id>` with
    `include = ["**/*.py"]` so `recall.indexer.index_source` can find it.
    Real git, real network -- called only from the controller's slow path.
    """
    repo_path = work_dir / instance.instance_id
    if not (repo_path / ".git").is_dir():
        subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                f"https://github.com/{instance.repo}",
                str(repo_path),
            ],
            check=True,
        )
    subprocess.run(
        ["git", "-C", str(repo_path), "checkout", instance.base_commit],
        check=True,
    )

    marker = repo_path / ".recall.toml"
    marker.write_text(
        tomli_w.dumps(
            {
                "source": {
                    "tag": f"swe-{instance.instance_id}",
                    "include": ["**/*.py"],
                    "exclude": ["**/.git/**"],
                }
            }
        )
    )
    return repo_path


def evaluate_instance(
    instance: SweInstance,
    store: PgVectorStore,
    embedder: Embedder,
    k: int = DEFAULT_K,
    config: RecallConfig | None = None,
) -> dict[str, Any]:
    """Score one instance's three retrieval arms against its gold files.

    Assumes the repo is ALREADY indexed under tag `swe-<instance_id>` -- this
    function does not index, and never calls index_source. The controller
    indexes (so it can run under its own memory cap and cache per repo);
    this only reads. Each arm queries the store independently at the top-`k`
    CHUNKS a real recall_search call would return, exactly as eval/harness.py
    does, then collapses to ranked files before scoring.
    """
    cfg = config or load_config()
    tag = f"swe-{instance.instance_id}"
    gold = set(instance.gold_files)

    qvec = embedder.embed_query(instance.problem_statement)

    hybrid_result = store.search(
        qvec=qvec,
        qtext=instance.problem_statement,
        sources=[tag],
        limit=k,
        k=cfg.rrf_k,
        w_dense=cfg.fusion_weight_dense,
        w_lexical=cfg.fusion_weight_lexical,
    )

    rankings = {
        "dense": _dedup_preserve_order(store.search_dense_only(qvec=qvec, sources=[tag], limit=k)),
        "lexical": _dedup_preserve_order(
            store.search_lexical_only(qtext=instance.problem_statement, sources=[tag], limit=k)
        ),
        "hybrid": chunks_to_ranked_files(hybrid_result.hits),
    }

    return {
        "instance_id": instance.instance_id,
        "repo": instance.repo,
        "difficulty": instance.difficulty,
        "n_gold": len(gold),
        "arms": {arm: file_metrics(ranked, gold, k) for arm, ranked in rankings.items()},
    }


ARMS = ("dense", "lexical", "hybrid")
METRIC_NAMES = ("recall_at_k", "precision_at_k", "f1_at_k", "mrr")


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean of each metric per arm, overall and (if present) by difficulty."""

    def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
        arm_means = {
            arm: {
                metric: (sum(r["arms"][arm][metric] for r in rows) / len(rows)) if rows else 0.0
                for metric in METRIC_NAMES
            }
            for arm in ARMS
        }
        return {"n": len(rows), "arms": arm_means}

    difficulties = sorted({r["difficulty"] for r in results if r.get("difficulty")})
    by_difficulty = {
        difficulty: summarise([r for r in results if r["difficulty"] == difficulty])
        for difficulty in difficulties
    }

    return {"overall": summarise(results), "by_difficulty": by_difficulty}


def print_report(agg: dict[str, Any]) -> None:
    """Readable table: dense vs lexical vs hybrid, file-level R@k/P@k/F1/MRR.

    Mirrors the honest-verdict style of eval/harness.py: a hybrid that does
    not beat both halves is reported as a loss, not dressed up.
    """
    overall = agg["overall"]
    print(f"\nSWE-bench retrieval precision -- {overall['n']} instance(s)\n")
    print(f"{'arm':10} {'R@k':>8} {'P@k':>8} {'F1@k':>8} {'MRR':>8}")
    print("-" * 46)
    for arm in ARMS:
        m = overall["arms"][arm]
        print(
            f"{arm:10} {m['recall_at_k']:>8.3f} {m['precision_at_k']:>8.3f} "
            f"{m['f1_at_k']:>8.3f} {m['mrr']:>8.3f}"
        )

    if agg["by_difficulty"]:
        print(f"\n{'difficulty':24} {'n':>4} {'arm':10} {'R@k':>8} {'MRR':>8}")
        print("-" * 58)
        for difficulty, summary in agg["by_difficulty"].items():
            for arm in ARMS:
                m = summary["arms"][arm]
                print(
                    f"{difficulty:24} {summary['n']:>4} {arm:10} "
                    f"{m['recall_at_k']:>8.3f} {m['mrr']:>8.3f}"
                )

    hybrid = overall["arms"]["hybrid"]["recall_at_k"]
    dense = overall["arms"]["dense"]["recall_at_k"]
    lexical = overall["arms"]["lexical"]["recall_at_k"]
    print("\noverall verdict (un-authored SWE-bench queries, file-level retrieval):")
    if hybrid > dense and hybrid > lexical:
        print("  Fusion beats both halves on real, un-authored issue-text queries.")
    elif hybrid < dense or hybrid < lexical:
        print(
            "  WARNING: hybrid LOSES to a half on this real-world code benchmark.\n"
            "  Do not ship this quietly -- investigate before trusting fusion on code."
        )
    else:
        print("  Hybrid ties a half on this benchmark (no fusion benefit here).")


def main() -> None:
    """THE SLOW REAL PATH: clones, indexes and scores real repos.

    Never exercised by the unit tests -- it needs network, git, a live
    Postgres and a live embedder, and real indexing takes on the order of
    tens of minutes per repo on a CPU-only box. Indexes each instance into
    its own tag and deletes it again afterwards, so runs do not accumulate.
    """
    parser = argparse.ArgumentParser(
        description=(
            "SWE-bench retrieval-precision eval. SLOW: clones and fully indexes "
            "each repo before scoring -- not for the fast unit-test loop."
        )
    )
    parser.add_argument(
        "--repos", nargs="*", default=None, help="repo filter, e.g. psf/requests pallets/flask"
    )
    parser.add_argument("--limit", type=int, default=None, help="max instances to evaluate")
    parser.add_argument("--k", type=int, default=DEFAULT_K, help="chunks/files retrieved per arm")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(".swebench-work"),
        help="scratch directory for repo clones",
    )
    args = parser.parse_args()

    print(
        "This is the SLOW real path: clones each repo, indexes it fully, scores, "
        "then deletes the tag. Expect on the order of tens of minutes per repo on "
        "a CPU-only box.\n"
    )

    instances = fetch_instances(repos=args.repos, limit=args.limit)
    print(f"{len(instances)} instance(s) to evaluate.\n")

    config = load_config()
    embedder = build_embedder(config)
    store = PgVectorStore(config.database_url)
    registry = Registry.load()
    args.work_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for instance in instances:
        print(f"=== {instance.instance_id} ({instance.repo}@{instance.base_commit[:8]}) ===")
        repo_path = prepare_repo(instance, args.work_dir)
        tag = registry.register(repo_path)
        try:
            report = index_source(tag, registry=registry, store=store, embedder=embedder)
            print(f"  indexed {report.files_indexed} file(s), {report.chunks_written} chunk(s)")
            results.append(evaluate_instance(instance, store, embedder, k=args.k, config=config))
        finally:
            store.delete_source(tag)

    print_report(aggregate(results))


if __name__ == "__main__":
    main()
