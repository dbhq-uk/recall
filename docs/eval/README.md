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

For each query the harness runs **three independent queries**, each asking for
the true top `limit` (10 by default — the same `limit` a real
`recall_search(limit=10)` call would use):

- **dense-only** — `store.search_dense_only(...)`, the true top-`limit` by
  cosine distance.
- **lexical-only** — `store.search_lexical_only(...)`, the true top-`limit` by
  the live lexical ranker (`bm25` via `pg_search` if the extension is genuinely
  live, `ts_rank_cd` if it has fallen back).
- **hybrid** — `store.search(...)`, exactly what a production `recall_search`
  call gets back: RRF over the production pool, at the configured `k` and
  fusion weights.

Baselines are **not** derived by re-sorting the fused hybrid pool. That would
bias them: a re-sorted pool only contains documents that survived fusion in
the first place, so it hands rank-credit to a document *because* fusion kept
it, not because the half in question actually found it convincingly. Each arm
queries the database independently instead, so `dense`, `lexical` and `hybrid`
Recall@10 are honestly comparable — none of them gets a head start from the
others' pool. `eval.metrics.fuse()` still exists, and is exercised directly by
`tests/test_metrics.py`, but the harness itself never calls it: it always goes
through `store.search(...)`, the real production path.

Recall@10 and MRR are computed per query, then averaged — overall and broken
down by `kind`. The per-query scores are *not* thrown away after averaging:
they're kept on the `ArmScore` (`recall_scores`, `mrr_scores`) so the harness
can bootstrap confidence intervals from them (see below).

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
  losing. `n` is printed next to every by-kind row — 10-15 queries is a small
  sample, and the point estimate on its own does not tell you how much to
  trust it.
- **`fusion_is_earning_its_keep`** — `True` only if hybrid beats *both* halves
  in aggregate *and* on every kind, where "beats" now means a statistically
  real win, not just a higher point estimate — see **Uncertainty** below. The
  harness prints a loud warning when it's `False`.

## Uncertainty: confidence intervals and the noise floor

10-15 queries per `kind` is not a lot of data. One query flipping from a miss
to a hit is worth ~7-10 percentage points of Recall@10 on a kind that size.
Reporting a bare point estimate ("hybrid: 0.600, dense: 0.800 → hybrid loses")
without saying how much sampling noise that comparison could plausibly be down
to is a claim the data can't support — exactly the kind of unearned confidence
CLAUDE.md's "honest failure" principle rules out.

So every arm's Recall@10 and MRR is now printed with a 95% confidence
interval, and every kind/aggregate verdict is decided by a **paired bootstrap
delta CI**, not by eyeballing point estimates or by comparing two per-arm CIs
for overlap. Both live in `eval/metrics.py`:

- **`bootstrap_ci(scores, confidence=0.95, seed=...)`** — the per-arm CI
  printed next to each Recall@10/MRR number. Resamples the arm's per-query
  scores with replacement many times, takes the mean of each resample, and
  reports the 2.5th/97.5th percentile of that distribution (Efron's
  nonparametric bootstrap — appropriate here because Recall@10 is 0/1-valued
  per query, not Gaussian at n=10).
- **`paired_bootstrap_delta_ci(arm_a, arm_b, confidence=0.95, seed=...)`** —
  the CI that actually decides a verdict. Resamples query *indices* (not the
  two score lists independently), so each query's dense score and hybrid
  score are always resampled together. This preserves the pairing and is the
  statistically correct way to ask "is hybrid actually better than dense on
  this golden set?" — per-query noise (an easy query vs. a hard query) mostly
  cancels instead of adding extra spread the way two independently-resampled
  CIs would.

**Non-overlapping per-arm CIs would imply a real difference, but overlapping
per-arm CIs do *not* imply "no real difference" — that is a well-known
statistical fallacy, because it ignores the (usually positive) covariance
between paired observations.** The harness never uses per-arm CI overlap to
decide a verdict; `eval/metrics.py` says so in a comment next to
`paired_bootstrap_delta_ci` so nobody "simplifies" it back. The only thing
that decides a verdict is whether the *paired delta* CI excludes zero.

This changes `kind_verdict_text` and `kind_beats_both_halves` into a three-way
call instead of two:

- **beats both halves** — hybrid's paired delta CI vs. *both* dense and
  lexical excludes zero on the positive side. A real win.
- **not distinguishable from noise at n=N** — hybrid's point estimate is
  higher than a half, but that half's paired delta CI includes zero. This is
  the new, honest state: at n=10-15 we often cannot tell a real 1-2 query
  improvement from resampling noise, and the harness now says so instead of
  claiming a win it can't back up. `fusion_is_earning_its_keep` returns
  `False` on this, on purpose — the whole point of this task was to stop that
  property from returning `True` on a difference the data can't support.
- **LOSES to a half** — hybrid's paired delta CI vs. a half excludes zero on
  the negative side. A real loss.

`bootstrap_ci` and `paired_bootstrap_delta_ci` both take a `seed` (fixed by
default) so a rerun of the harness, or CI, reproduces the identical interval —
without a fixed seed, the same golden-set run could print a different verdict
on every invocation, which would be its own kind of dishonesty. Both are
stdlib-only (`random` + arithmetic); no `numpy`/`scipy` dependency was added.

`ArmScore.recall_scores` / `ArmScore.mrr_scores` carry the per-query scores
that make all of this possible. They're optional (default `None`) for
backward compatibility with any `Report` built from aggregates alone — in that
case the verdict falls back to the old point-estimate comparison, because
there is nothing to bootstrap.

## The numbers we measured

Re-measured **17 July 2026** with the interval-aware harness. The previous
version of this table was a bare point estimate over a *smaller* fixture (484
chunks from 52 files); the corpus has since grown, so it was stale on the
corpus as well as on the statistics, and it has been replaced rather than
caveated.

Run on the real environment: Postgres 16 + `pgvector` + `pg_search` (BM25
genuinely live — the harness prints `lexical ranker: bm25`), Ollama
`nomic-embed-text` (768-dim, CPU-only). 73 fixture files indexed to **651
chunks**, 0 skipped, 0 pruned, 0 fell back to line-window chunking. Shipped
config: RRF `k = 10`, `w_dense = 0.7`, `w_lexical = 0.3`, `limit = 10`.

### Overall (40 queries)

| arm | Recall@10 | MRR |
|---|---|---|
| dense-only | 0.900 [0.800–0.975] | 0.735 [0.617–0.849] |
| lexical-only (bm25) | 0.725 [0.575–0.850] | 0.510 [0.371–0.646] |
| **hybrid** | **0.875 [0.774–0.975]** | **0.645 [0.530–0.761]** |

`fusion_is_earning_its_keep` is **`False`**, and the harness says so loudly:
hybrid does not beat both halves. **Dense-only is the best arm on this fixture
on both metrics.** Note this reverses the previous table's headline, which
claimed fusion won in aggregate — on the grown corpus it does not.

### By kind

| kind | arm | Recall@10 | MRR |
|---|---|---|---|
| semantic (15) | dense | 0.733 [0.467–0.933] | 0.582 [0.350–0.808] |
| semantic (15) | lexical | 0.267 [0.067–0.467] | 0.068 [0.011–0.144] |
| semantic (15) | **hybrid** | **0.667 [0.400–0.867]** | **0.461 [0.255–0.678]** |
| lexical (15) | dense | 1.000 [1.000–1.000] | 0.867 [0.767–0.967] |
| lexical (15) | lexical | 1.000 [1.000–1.000] | 0.717 [0.550–0.867] |
| lexical (15) | **hybrid** | **1.000 [1.000–1.000]** | **0.800 [0.667–0.933]** |
| hybrid (10) | dense | 1.000 [1.000–1.000] | 0.767 [0.583–0.934] |
| hybrid (10) | lexical | 1.000 [1.000–1.000] | 0.863 [0.650–1.000] |
| hybrid (10) | **hybrid** | **1.000 [1.000–1.000]** | **0.687 [0.480–0.883]** |

Verdicts, now interval-decided rather than eyeballed:

- **semantic** — *not distinguishable from noise at n=15*. Hybrid's point
  estimate trails dense (0.667 vs 0.733), but the paired delta CI includes
  zero. The old table read this same gap as fusion "LOSING"; at this sample
  size that claim was never supportable. This is precisely what the interval
  work was for.
- **lexical** and **hybrid** kinds — *ties*. Every arm saturates Recall@10 at
  1.000, so there is nothing for fusion to improve. A saturated metric is not
  evidence of success; it is evidence the metric has stopped discriminating.

### k sweep (hybrid arm, all 40 queries)

| k | Recall@10 | MRR |
|---:|---:|---:|
| 1 | 0.875 | 0.720 |
| 5 | 0.900 | 0.706 |
| **10 (default)** | 0.875 | 0.645 |
| 20 | 0.875 | 0.631 |
| 40 | 0.900 | 0.627 |
| 60 | 0.900 | 0.622 |
| 80 | 0.900 | 0.622 |
| 120 | 0.900 | 0.622 |
| 200 | 0.900 | 0.622 |

Flat within noise. See **On `k`** above for the paired test that settles the
`k=10` vs `k=60` question (answer: indistinguishable).

## Honest reading: does fusion earn its keep?

**On this fixture: no.** `fusion_is_earning_its_keep` is `False` and the
harness's loud-warning branch fires. Dense-only (0.900 / 0.735) beats hybrid
(0.875 / 0.645) in aggregate, and no kind shows a statistically real fusion
win.

A previous version of this section reported the opposite headline — "overall,
yes by a nose" — from an aggregate where hybrid (0.800) edged dense (0.750) on
a smaller corpus. That is worth leaving on the record, because the reversal is
instructive twice over:

- The old aggregate "win" was **arithmetic, not retrieval**. It came from the
  lexical queries' near-perfect scores dragging the hybrid mean up while
  dragging dense's mean down. Splitting by kind dissolved it even then. An
  aggregate over a deliberately mixed query set is a weighted average of
  unrelated things, and it means very little on its own.
- The old by-kind commentary then **over-claimed in the other direction**,
  calling dense-vs-hybrid on `semantic` "a wide margin" and "the single most
  important number in this report". With intervals, today's equivalent gap is
  *not distinguishable from noise at n=15*. Confident prose about a 0.07
  difference across 15 queries was never supportable — in either direction.

What survives both readings is the honest, boring finding: **on a small,
semantic-skewed, self-authored fixture, a strong dense retriever is hard to
improve on by fusing a weak lexical half into it.** On `lexical` and `hybrid`
kinds every arm now saturates Recall@10 at 1.000, so the fixture has stopped
discriminating there at all — that is a limitation of the corpus, not a
property of fusion.

This is also why the BEIR results (`docs/design.md`, README) matter more than
this table: on external, un-authored corpora with real relevance labels,
hybrid *does* win. Two corpora disagreeing is not a contradiction to explain
away — it is the actual finding. Fusion's value depends on the query
distribution, and ours is not representative of everyone's.

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

**The shipped default is `k = 10`.** This section previously concluded "`k=60`
stays" — and then the default was changed to 10 anyway, in a commit about
fusion weights, without a word. That drift is the reason this repo now keeps a
decision log (`docs/design.md`) and the reason the harness reports intervals
instead of bare point estimates: a sweep that prints only means is exactly the
instrument that lets a null result get read as a finding.

Re-measured 17 July 2026 (real Ollama, real BM25, `limit=10`), the sweep is
flat: Recall@10 sits at 0.875–0.900 across every `k` from 1 to 200, and MRR
declines gently from 0.720 (`k=1`) to 0.622 (`k≥60`). The paired bootstrap
settles it — `k=10` vs `k=60` is indistinguishable on both metrics:

| comparison | delta (k=10 − k=60) | 95% CI | verdict |
|---|---:|---|---|
| Recall@10 | −0.025 | [−0.075, +0.000] | includes 0 |
| MRR | +0.023 | [−0.019, +0.076] | includes 0 |

So `k=10` is kept as a **prior, not a result**: a low `k` weights the head of
each ranking, which suits top-10 retrieval into an agent's context. The old
reasoning above was sound — there was never evidence to justify moving off 60,
and there is still none. What was wrong was moving anyway and not saying so.
Revisit if the golden set grows enough to separate the two.

## Is the corpus/chunking bet working?

Dense-only Recall@10 on the 15 `semantic` queries — the ones deliberately
phrased to share no vocabulary with their answers — is **0.733 [95% CI
0.467–0.933]**, against a lexical arm that manages 0.267 on the same queries.
That gap is the design's central chunking bet (embedding the heading trail
alongside the body text) doing real semantic work: these are queries grep
cannot serve, and dense retrieval serves most of them.

Read the interval, though, before celebrating: at n=15 that estimate is
consistent with anything from 0.467 to 0.933. It is reasonable evidence the
bet works. It is not a precise measurement of *how well*, and this corpus
cannot make it one.

The `lexical` and `hybrid` kinds now saturate Recall@10 at 1.000 on every arm.
That is not a good sign — it means those 25 queries have stopped
discriminating between approaches entirely, and any future change will look
free on them regardless of its merit. **The most valuable work available to
this harness is not another fusion tweak; it is harder queries and more of
them.** `tests/test_golden_set.py` guards against leakage and kind-mix drift,
but it cannot make a saturated metric informative.
