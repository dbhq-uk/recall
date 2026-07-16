"""BEIR evaluation adapter.

The golden set in eval/golden.toml is ours: we wrote the queries and the
relevance labels, and it once gave the OPPOSITE answer to a real, live
decision recorded in a real note. That is a synthetic-eval failure mode, not
a fusion failure mode -- but it means the golden set cannot be the only
number that matters after all. BEIR is the standard IR benchmark: external
labels, a fixed corpus, and published baselines (BM25, DPR, ANCE, TAS-B,
ColBERT) to compare against, so our numbers mean something to someone who has
never read this repo.

Two datasets, both downloaded ahead of time to a local directory (see
--dataset): SciFact (5,183 docs / 300 test queries, binary relevance) and
NFCorpus (3,633 docs / 323 test queries, graded relevance). Each ships as
corpus.jsonl, queries.jsonl and qrels/test.tsv -- see load_corpus,
load_queries and load_qrels for the exact shapes and the gotchas in them.

recall indexes and retrieves CHUNKS; BEIR qrels judge DOCUMENTS. The bridge
is two-way:
  - materialise_corpus/doc_id_from_rel_path -- one file per doc, named
    <doc_id>.md, so a chunk's rel_path recovers its doc_id exactly.
  - pool_chunks_to_docs -- max-pool chunk scores up to doc scores. This is
    mandatory, not cosmetic: without it the run's keys are not doc_ids and
    the comparison to qrels (and to published baselines) is meaningless.

Two speeds live in this one module, exactly as eval/swebench.py:
  - Fast, pure, unit-tested: load_corpus, load_queries, load_qrels,
    materialise_corpus, doc_id_from_rel_path, pool_chunks_to_docs,
    ranked_run_from_paths, evaluate_run, print_report. tests/test_beir.py
    exercises these with no network, no database and no indexing.
  - Slow, real, __main__-only: run_dataset (queries an already-indexed
    store) and main()'s --index path (materialises the corpus and runs a
    full recall index over it -- on the order of hours on a CPU-only box for
    these corpus sizes). Neither is exercised by the test suite.

Run (assumes `--tag` is already indexed):
    python -m eval.beir --dataset /tmp/beir_probe/scifact --tag beir-scifact

Run (slow: materialises + indexes first):
    python -m eval.beir --dataset /tmp/beir_probe/scifact --tag beir-scifact --index
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Protocol

import tomli_w
from ranx import Qrels, Run, evaluate

from recall.config import Registry, load_config
from recall.embedders import Embedder, build_embedder
from recall.indexer import index_source
from recall.store.pgvector import PgVectorStore

DEFAULT_K = 10
MATERIALISED_DIRNAME = ".materialised"

# NDCG@10 from the BEIR paper (Thakur et al., 2021), Table 2/3. This is THE
# BEIR metric -- what every published baseline below is reported in.
PUBLISHED_BASELINES: dict[str, dict[str, float]] = {
    "scifact": {"BM25": 0.665, "ColBERT": 0.671, "TAS-B": 0.643, "ANCE": 0.507, "DPR": 0.318},
    "nfcorpus": {"BM25": 0.325, "ColBERT": 0.305, "TAS-B": 0.319, "ANCE": 0.237, "DPR": 0.189},
}

# If our lexical arm's NDCG@10 falls below this fraction of published BM25,
# something is badly wrong with the lexical half on this corpus (not merely
# "ts_rank_cd is weaker than BM25" -- an order-of-magnitude gap).
LEXICAL_COLLAPSE_RATIO = 0.5


# ---------------------------------------------------------------------------
# Loading -- pure, unit-tested directly. No network, no database.
# ---------------------------------------------------------------------------


def load_corpus(path: Path) -> dict[str, dict[str, str]]:
    """doc_id -> {"title": ..., "text": ...}, from a BEIR corpus.jsonl.

    Each line is `{"_id": "...", "title": "...", "text": "..."}`.
    """
    corpus: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            corpus[row["_id"]] = {"title": row.get("title", ""), "text": row.get("text", "")}
    return corpus


def load_qrels(path: Path) -> dict[str, dict[str, int]]:
    """{qid: {doc_id: relevance}} from a BEIR qrels TSV.

    BEIR qrels files carry a header row (`query-id\tcorpus-id\tscore`) --
    skip it, or it parses as a bogus judgment. Scores are ints: binary (0/1)
    for SciFact, graded for NFCorpus.
    """
    qrels: dict[str, dict[str, int]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        next(reader, None)  # header row: query-id, corpus-id, score
        for row in reader:
            if not row:
                continue
            qid, doc_id, score = row[0], row[1], row[2]
            qrels.setdefault(qid, {})[doc_id] = int(score)
    return qrels


def load_queries(path: Path, qrels: dict[str, dict[str, int]]) -> dict[str, str]:
    """qid -> query text, filtered to only the qids present in `qrels`.

    CRITICAL GOTCHA: a BEIR dataset's queries.jsonl holds every split's
    queries (train/dev/test) in one file, not just the test split. Loading it
    unfiltered inflates the query count by roughly 10x and scores against
    queries that have no test-split judgments at all -- silently wrong, not
    an error. Filtering to `set(qrels)` is what makes this the TEST split.
    """
    wanted = set(qrels)
    queries: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            qid = row["_id"]
            if qid in wanted:
                queries[qid] = row["text"]
    return queries


# ---------------------------------------------------------------------------
# Materialising the corpus so recall can index it as an ordinary source.
# ---------------------------------------------------------------------------


def materialise_corpus(corpus: dict[str, dict[str, str]], out_dir: Path, tag: str) -> None:
    """Write each doc as `out_dir/<doc_id>.md`, plus a `.recall.toml` marker.

    The filename stem IS the doc_id -- doc_id_from_rel_path is its exact
    inverse -- so a chunk's rel_path recovers the BEIR doc_id it came from
    without recall's indexer or store ever needing to know BEIR exists.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for doc_id, doc in corpus.items():
        title = doc.get("title", "")
        text = doc.get("text", "")
        (out_dir / f"{doc_id}.md").write_text(f"# {title}\n\n{text}\n", encoding="utf-8")

    marker = out_dir / ".recall.toml"
    marker.write_text(tomli_w.dumps({"source": {"tag": tag, "include": ["**/*.md"]}}))


def doc_id_from_rel_path(rel_path: str) -> str:
    """Inverse of materialise_corpus's naming: strip directory and `.md`."""
    return PurePosixPath(rel_path).stem


# ---------------------------------------------------------------------------
# Scoring -- chunk-level retrieval pooled to doc-level. BEIR qrels are
# doc-level; recall's index is chunk-level. Without this bridge the run's
# keys would not be doc_ids, and evaluate_run against qrels would compare
# apples to chunk fragments.
# ---------------------------------------------------------------------------


class _HasRelPathAndScore(Protocol):
    rel_path: str
    score: float


def pool_chunks_to_docs(hits: Iterable[_HasRelPathAndScore]) -> dict[str, float]:
    """MAX-POOL chunk hits to doc-level scores: a doc's score is the MAX over
    its chunks, never the sum or the mean.

    This is mandatory, not a stylistic choice: BEIR qrels are doc-level and
    recall's retrieval is chunk-level, so without pooling there is no run to
    compare against qrels at all. Max, not sum, so a long document does not
    win purely for having many mediocre chunks -- it must have at least one
    chunk that is a genuinely strong match.
    """
    scores: dict[str, float] = {}
    for hit in hits:
        doc_id = doc_id_from_rel_path(hit.rel_path)
        if doc_id not in scores or hit.score > scores[doc_id]:
            scores[doc_id] = hit.score
    return scores


def ranked_run_from_paths(rel_paths: Iterable[str]) -> dict[str, float]:
    """Assign descending synthetic scores by rank to an ordered rel_path list.

    search_dense_only and search_lexical_only return ordered rel_paths with
    no scores. ranx's NDCG needs scores to recover an order, so a strictly
    descending sequence (1/(rank+1)) preserves exactly the order recall
    returned, with no scores of its own invented. Deduplicates by doc_id,
    keeping the best (earliest) rank a doc was seen at.
    """
    scores: dict[str, float] = {}
    for rank, rel_path in enumerate(rel_paths):
        doc_id = doc_id_from_rel_path(rel_path)
        candidate = 1.0 / (rank + 1)
        if doc_id not in scores or candidate > scores[doc_id]:
            scores[doc_id] = candidate
    return scores


# ---------------------------------------------------------------------------
# Evaluation -- ranx is the standard BEIR toolkit's reference metric
# implementation; PUBLISHED_BASELINES is what we compare against;
# print_report is the honest verdict.
# ---------------------------------------------------------------------------


def evaluate_run(
    qrels: dict[str, dict[str, int]], run: dict[str, dict[str, float]], k: int = 10
) -> dict[str, float]:
    """ndcg@k, recall@k, mrr, map@k via ranx.

    NDCG@k is THE BEIR metric -- what PUBLISHED_BASELINES is reported in.
    make_comparable=True adds an empty result for any query the run has no
    hits for at all (a real possibility -- an arm can legitimately return
    nothing) rather than raising a hard mismatch error.
    """
    ranx_qrels = Qrels(qrels)
    ranx_run = Run(run)
    metrics = [f"ndcg@{k}", f"recall@{k}", "mrr", f"map@{k}"]
    scores = evaluate(ranx_qrels, ranx_run, metrics, make_comparable=True)
    return {name: float(value) for name, value in scores.items()}


def print_report(dataset: str, arm_scores: dict[str, dict[str, float]]) -> None:
    """Table of our dense/lexical/hybrid NDCG@10 vs published baselines.

    Key interpretation, spelled out because it is easy to misread: on
    SciFact, published BM25 (0.665) is roughly DOUBLE published DPR (0.318).
    A hybrid score that collapses toward the dense-only baselines (DPR/ANCE)
    rather than sitting near or above BM25 is not "dense winning honestly" --
    on a lexical-friendly benchmark like this it usually means fusion has
    silently become dense-only (the lexical half found nothing, or next to
    nothing, and RRF/weighted-RRF degenerated to the dense ranking with extra
    steps). We flag this loudly whenever the lexical arm itself is far below
    published BM25, since that is the root cause, not merely a symptom.
    """
    baselines = PUBLISHED_BASELINES.get(dataset, {})
    k_key = "ndcg@10"

    print(f"\nBEIR dataset: {dataset}\n")
    print(f"{'arm':10} {'NDCG@10':>10} {'Recall@10':>10} {'MRR':>8} {'MAP@10':>10}")
    print("-" * 52)
    for arm in ("dense", "lexical", "hybrid"):
        s = arm_scores.get(arm)
        if not s:
            continue
        print(
            f"{arm:10} {s.get(k_key, float('nan')):>10.3f} "
            f"{s.get('recall@10', float('nan')):>10.3f} "
            f"{s.get('mrr', float('nan')):>8.3f} "
            f"{s.get('map@10', float('nan')):>10.3f}"
        )

    if baselines:
        print(f"\npublished baselines (NDCG@10) for {dataset}:")
        for name, score in baselines.items():
            print(f"  {name:10} {score:>6.3f}")

    print("\nverdict:")
    lexical_ndcg = arm_scores.get("lexical", {}).get(k_key)
    hybrid_ndcg = arm_scores.get("hybrid", {}).get(k_key)
    dense_ndcg = arm_scores.get("dense", {}).get(k_key)
    bm25 = baselines.get("BM25")
    dpr = baselines.get("DPR")

    lexical_collapsed = (
        bm25 is not None
        and lexical_ndcg is not None
        and lexical_ndcg < bm25 * LEXICAL_COLLAPSE_RATIO
    )
    if lexical_collapsed:
        print(
            f"  WARNING: our lexical arm (NDCG@10={lexical_ndcg:.3f}) is far below published "
            f"BM25 ({bm25:.3f}) on {dataset}. The lexical half is not doing real lexical "
            "retrieval here -- check store.lexical_ranker() and whether pg_search's bm25 "
            "index actually exists."
        )
        if bm25 is not None and dpr is not None and hybrid_ndcg is not None:
            print(
                f"  Because BM25 ({bm25:.3f}) >> DPR ({dpr:.3f}) on this benchmark: if our "
                f"hybrid (NDCG@10={hybrid_ndcg:.3f}) sits near the dense-only baselines "
                "(DPR/ANCE) rather than near BM25, that is fusion having silently become "
                "dense-only -- not dense legitimately winning. Do not report this as a "
                "healthy hybrid result."
            )

    if hybrid_ndcg is not None and dense_ndcg is not None and lexical_ndcg is not None:
        if hybrid_ndcg > dense_ndcg and hybrid_ndcg > lexical_ndcg:
            print("  Fusion beats both halves on NDCG@10 for this dataset.")
        elif hybrid_ndcg < dense_ndcg or hybrid_ndcg < lexical_ndcg:
            print(
                "  WARNING: hybrid LOSES to a half on NDCG@10 for this dataset. Do not ship "
                "this quietly -- investigate before trusting fusion here."
            )
        else:
            print("  Hybrid ties a half on NDCG@10 for this dataset (no fusion benefit here).")

    if bm25 is not None:
        arm_ndcgs = (("dense", dense_ndcg), ("lexical", lexical_ndcg), ("hybrid", hybrid_ndcg))
        for arm, ndcg in arm_ndcgs:
            if ndcg is None:
                continue
            gap = ndcg - bm25
            sign = "+" if gap >= 0 else ""
            print(f"  {arm:10} vs published BM25: {sign}{gap:.3f}")


# ---------------------------------------------------------------------------
# The runner -- assumes `tag` is ALREADY indexed. Needs a live store and
# embedder, so it is not exercised by the fast unit-test suite.
# ---------------------------------------------------------------------------


def run_dataset(
    dataset_dir: Path,
    tag: str,
    store: PgVectorStore,
    embedder: Embedder,
    k: int = DEFAULT_K,
) -> dict[str, dict[str, dict[str, float]]]:
    """Score every test-split query against an already-indexed source.

    For each test query: dense-only, lexical-only, hybrid (production config
    weights) -- each queried independently at the true top-k CHUNKS, exactly
    as eval/harness.py and eval/swebench.py do, never derived by re-sorting
    the fused pool. Hybrid hits are max-pooled to doc-level
    (pool_chunks_to_docs); the unscored dense/lexical rel_path lists are
    turned into rank-ordered scores (ranked_run_from_paths). Returns
    {"dense": run, "lexical": run, "hybrid": run}, each a ranx-shaped
    {qid: {doc_id: score}} ready for evaluate_run.
    """
    cfg = load_config()
    qrels = load_qrels(dataset_dir / "qrels" / "test.tsv")
    queries = load_queries(dataset_dir / "queries.jsonl", qrels)

    runs: dict[str, dict[str, dict[str, float]]] = {"dense": {}, "lexical": {}, "hybrid": {}}
    for qid, text in queries.items():
        qvec = embedder.embed_query(text)

        dense_paths = store.search_dense_only(qvec=qvec, sources=[tag], limit=k)
        lexical_paths = store.search_lexical_only(qtext=text, sources=[tag], limit=k)
        hybrid_result = store.search(
            qvec=qvec,
            qtext=text,
            sources=[tag],
            limit=k,
            k=cfg.rrf_k,
            w_dense=cfg.fusion_weight_dense,
            w_lexical=cfg.fusion_weight_lexical,
        )

        runs["dense"][qid] = ranked_run_from_paths(dense_paths)
        runs["lexical"][qid] = ranked_run_from_paths(lexical_paths)
        runs["hybrid"][qid] = pool_chunks_to_docs(hybrid_result.hits)

    return runs


def main() -> None:
    """THE SLOW REAL PATH (with --index): materialises and fully indexes the
    corpus before scoring. Without --index, assumes `--tag` is already
    indexed and only reads. Never exercised by the unit tests -- --index
    needs a live Postgres and a live embedder, and real indexing runs on the
    order of hours on a CPU-only box for these corpus sizes.
    """
    parser = argparse.ArgumentParser(
        description="BEIR evaluation adapter for recall: dense/lexical/hybrid NDCG@10 vs "
        "published baselines."
    )
    parser.add_argument(
        "--dataset", type=Path, required=True, help="BEIR dataset dir, e.g. /tmp/beir_probe/scifact"
    )
    parser.add_argument("--tag", required=True, help="recall source tag to index/query under")
    parser.add_argument("--k", type=int, default=DEFAULT_K, help="chunks/docs retrieved per arm")
    parser.add_argument(
        "--index", action="store_true", help="materialise the corpus and index it first (slow path)"
    )
    args = parser.parse_args()

    dataset_name = args.dataset.name
    config = load_config()
    embedder = build_embedder(config)
    store = PgVectorStore(config.database_url)

    if args.index:
        print(f"Materialising + indexing {args.dataset} under tag {args.tag!r} (slow path)...")
        corpus = load_corpus(args.dataset / "corpus.jsonl")
        print(f"  {len(corpus)} document(s) in corpus.jsonl")
        materialise_dir = args.dataset / MATERIALISED_DIRNAME
        materialise_corpus(corpus, materialise_dir, args.tag)
        registry = Registry.load()
        registry.register(materialise_dir)
        report = index_source(args.tag, registry=registry, store=store, embedder=embedder)
        print(f"  indexed {report.files_indexed} file(s), {report.chunks_written} chunk(s)")

    qrels = load_qrels(args.dataset / "qrels" / "test.tsv")
    queries = load_queries(args.dataset / "queries.jsonl", qrels)
    print(
        f"\nScoring {dataset_name} (tag={args.tag!r}, k={args.k}): {len(queries)} test query(ies)"
    )

    runs = run_dataset(args.dataset, args.tag, store, embedder, k=args.k)
    arm_scores = {arm: evaluate_run(qrels, run, k=args.k) for arm, run in runs.items()}
    print_report(dataset_name, arm_scores)


if __name__ == "__main__":
    main()
