# The golden-query harness

`eval/harness.py` is the only number in this project that matters. Everything
before it — walker, chunkers, embedders, the pgvector store, RRF — was
plumbing. This is what tells us whether recall actually retrieves.

It answers one question honestly: **does fusing dense and lexical search with
RRF actually beat either half alone?** If it doesn't, we say so here rather
than quietly shipping a fusion that fuses nothing.

## How it works

`eval/golden.toml` has 40 hand-written queries against the fixture corpus in
`eval/fixture/` (40 markdown notes + 12 source files across five topic areas),
each tagged `semantic` (15), `lexical` (15) or `hybrid` (10) and pointing at
the `rel_path`(s) that genuinely answer it. `tests/test_golden_set.py` guards
the set itself: forty queries, the right kind-mix, every `relevant` path
exists, and — the anti-contamination check — no `semantic` query shares more
than one significant word with its target, so semantic queries can't win by
being grep in disguise.

For each query the harness fetches **one** pool of 200 hits (`store.search(...,
limit=200)`, `pool = limit * 3 = 600` under the hood) with both `dense_rank`
and `lexical_rank` attached to every hit. From that single pool it derives all
three rankings in Python:

- **dense-only** — sort by `dense_rank`
- **lexical-only** — sort by `lexical_rank`
- **hybrid** — `eval.metrics.fuse(dense_ranks, lexical_ranks, k)`, i.e. real RRF

No extra queries, no protocol change — RRF is a pure function of ranks, so it
can be recomputed for any `k` after the fact. Recall@10 and MRR are computed
per query and averaged, overall and broken down by `kind`.

## Running it

```bash
export RECALL_DATABASE_URL="postgresql://recall@localhost:5432/recall"
uv run recall init
uv run recall register eval/fixture
uv run recall index fixture      # slow on CPU-only Ollama — several minutes for 52 files

uv run python -m eval.harness            # score at the default k=60
uv run python -m eval.harness --k 20     # score at a specific k
uv run python -m eval.harness --sweep    # sweep k over {1,5,10,20,40,60,80,120,200}
```

## How to read the report

- **arm** — `dense`, `lexical`, `hybrid`. Never read a number without checking
  which arm it's from — a dense-only Recall@10 and a hybrid Recall@10 look
  identical in isolation and mean very different things.
- **lexical ranker** — printed at the top of every run. `bm25` means the
  `pg_search` extension and its index are genuinely live; `ts_rank_cd` means
  they are not, and the lexical arm is a weaker, unsaturated ranker. A hybrid
  number is only as honest as the ranker it's fused from.
- **by kind** — the same three arms, restricted to the 15 `semantic`, 15
  `lexical` or 10 `hybrid` queries. This is where the real signal is: the
  overall row can look fine while masking a kind where fusion is actively
  losing.
- **`fusion_is_earning_its_keep`** — `True` only if the *overall* hybrid
  Recall@10 beats *both* the overall dense-only and lexical-only Recall@10.
  The harness prints a loud warning when it's `False`. Note that this checks
  the aggregate only — see below for why the by-kind table still needs reading
  even when it says `True`.

## The numbers we measured

Run on the real environment: Postgres 16 + `pgvector` + `pg_search` (BM25
genuinely live, confirmed by `recall doctor`), Ollama `nomic-embed-text`
(768-dim, CPU-only). 52 fixture files indexed to **484 chunks**, 0 skipped, 0
pruned. RRF `k = 60` (the configured default) unless noted.

### Overall (40 queries)

| arm | Recall@10 | MRR |
|---|---:|---:|
| dense-only | 0.750 | 0.466 |
| lexical-only (bm25) | 0.475 | 0.431 |
| **hybrid (RRF, k=60)** | **0.800** | **0.591** |

By this aggregate view, `fusion_is_earning_its_keep` is `True`: hybrid beats
both halves. That is the headline the harness itself prints. **It is not the
whole story — see below.**

### By kind

| kind | arm | Recall@10 | MRR |
|---|---|---:|---:|
| semantic (15) | dense | 0.800 | 0.468 |
| semantic (15) | lexical | 0.067 | 0.041 |
| semantic (15) | **hybrid** | **0.600** | **0.294** |
| lexical (15) | dense | 0.600 | 0.376 |
| lexical (15) | lexical | 1.000 | 0.947 |
| lexical (15) | **hybrid** | **1.000** | **0.922** |
| hybrid (10) | dense | 0.900 | 0.598 |
| hybrid (10) | lexical | 0.300 | 0.242 |
| hybrid (10) | **hybrid** | **0.800** | **0.538** |

### k sweep (hybrid arm, all 40 queries)

| k | Recall@10 | MRR |
|---:|---:|---:|
| 1 | 0.800 | 0.611 |
| 5 | 0.800 | 0.614 |
| 10 | 0.800 | 0.609 |
| 20 | 0.800 | 0.597 |
| 40 | 0.800 | 0.588 |
| **60 (default)** | 0.800 | 0.591 |
| 80 | 0.875 | 0.568 |
| 120 | 0.825 | 0.542 |
| 200 | 0.850 | 0.560 |

## Honest reading: does fusion earn its keep?

**Overall, yes by a nose — but on the two query kinds fusion exists for,
no.** The aggregate `fusion_is_earning_its_keep` property is `True`
(hybrid 0.800 > dense 0.750 and > lexical 0.475), and the harness's own
loud-warning branch does not fire. Taken at face value that says RRF is
paying for itself. Reading the by-kind table says something more
uncomfortable:

- **On the 15 `semantic` queries**, dense-only alone (0.800 / 0.468) beats
  hybrid (0.600 / 0.294) by a wide margin. Lexical is nearly useless here
  (0.067), as designed — these queries deliberately share no significant
  vocabulary with their answers. Fusing in a near-useless lexical ranking
  *actively hurts*.
- **On the 10 `hybrid` queries — the ones purpose-built to need both
  halves — dense-only alone (0.900 / 0.598) also beats hybrid (0.800 /
  0.538).** This is the single most important number in this report: on
  exactly the query set designed to showcase RRF, RRF underperforms doing
  nothing but dense search.
- **On the 15 `lexical` queries**, lexical-only is already almost perfect
  (1.000 / 0.947) and hybrid ties it on Recall@10 (1.000) but is slightly
  *worse* on MRR (0.922). Fusion does not improve the query kind it should be
  safest on; it merely doesn't break it.

So the only reason the *overall* number looks like a win is arithmetic: the
lexical queries' near-perfect scores survive fusion and drag the hybrid
average above dense-only, while dense-only's own average is dragged down by
the lexical queries, where it is comparatively weak (0.600). Once you split
by kind, hybrid does not beat dense-only on either kind where dense-only
still had headroom to lose.

**Why this happens — verified by hand on the `hybrid`-kind queries with a
scratch script.** RRF scores a document by summing `1/(k+rank)` across the
lists it appears in. A document that is a strong #1 in dense but *absent*
from the lexical result set (its content genuinely doesn't share query terms
— true for 7 of the 10 `hybrid` queries here) gets only the dense term. A
different, wrong document that is a mediocre #5-ish in *both* dense and
lexical can out-score it by simple addition. Concretely: for q039 ("what the
1.4x risk buffer on a fixed-price quote is actually for"), the correct
document sits at dense rank 5 and is absent from the lexical pool entirely —
and RRF drops it out of the top 10 altogether, where dense-only alone had it
comfortably inside. This is exactly the failure mode the design doc names up
front: *"convex combination may beat RRF outright."* On this corpus, for
queries where one half is simply silent rather than merely weak, it does.

**This is not a case for ripping out RRF.** It still wins outright on the
aggregate, and on `lexical` queries (where BM25 is strong) it does no harm.
But it is a real, measured finding, not a flattering one, and it should
inform the roadmap: a cross-encoder reranker (already first on the v1+
roadmap) or a convex-combination fusion mode are both better answers to
"one half found it convincingly, the other didn't look" than RRF's pure
rank-sum.

## On `k`

The sweep shows Recall@10 is flat at 0.800 for every `k` from 1 to 60, then
rises to 0.825–0.875 for `k` in {80, 120, 200} — but MRR *falls* as `k` grows
past 5–10, and the movement above `k=60` is a handful of queries flipping
(each of the 40 queries is worth 2.5 percentage points of Recall@10, so these
swings are close to the noise floor of a 40-query set). The best `k` by MRR is
5 (0.614), barely ahead of the default 60 (0.591) — a difference smaller than
one query. **This is not far enough from 60 to justify changing the
default.** `k=60` stays; if the golden set grows enough to make the sweep less
noisy, revisit.

## Is the corpus/chunking bet working?

Dense-only Recall@10 on the 15 `semantic` queries — the ones deliberately
phrased to share no vocabulary with their answers — is 0.800. That is
reasonable evidence that the design's central chunking bet (embedding the
heading trail alongside the body text) is delivering real semantic retrieval,
not just prose. Nothing here scores suspiciously close to 1.0 across the
board, so there is no reason to suspect query leakage or a too-small corpus
(`tests/test_golden_set.py` also actively guards against both).
