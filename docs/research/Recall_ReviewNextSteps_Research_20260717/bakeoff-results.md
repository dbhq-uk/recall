# Embedder bake-off: measured results

*17 July 2026 · nomic-embed-text (v1) vs nomic-embed-text-v2-MoE · BEIR SciFact*

The 16 July report named the embedder upgrade as recall's "single highest-ROI
change… stronger *and* faster, the rare unambiguous win," and the 17 July
review made running the bake-off the top quality experiment. This is that
experiment, run. The headline: **it is not an unambiguous win, and the ways it
falls short were only visible because we measured instead of trusting the
leaderboard.**

## Method

Both arms indexed the **same** BEIR SciFact corpus (5,183 docs → 5,746 chunks)
**scifact-only** into the same database, changing nothing but the embedder.
300 test queries, NDCG@10, three arms (dense / lexical / hybrid) each queried
independently at top-10. Difference between arms tested with the paired
bootstrap over the 300 per-query scores (`eval.metrics.paired_bootstrap_delta_ci`),
not by eyeballing aggregates.

**Built-in control.** Because both indexes are scifact-only and BM25 is
embedder-independent, the lexical arm *must* score identically across the two.
It did, to four decimals (0.6446 = 0.6446, delta CI [0, 0]). That is the
receipt that the corpus composition, chunking and harness were genuinely held
constant and only the embedder moved.

## Quality

| arm | v1 NDCG@10 | v2-MoE NDCG@10 | delta (v2−v1) | 95% CI | verdict |
|---|---|---|---|---|---|
| dense | 0.7039 | 0.7270 | **+0.0231** | [+0.0026, +0.0450] | **v2-MoE wins (excludes 0)** |
| lexical | 0.6446 | 0.6446 | +0.0000 | [0, 0] | control — identical by construction |
| hybrid | 0.7147 | 0.7283 | +0.0136 | [−0.0077, +0.0357] | indistinguishable from noise |

**v2-MoE genuinely improves the dense retriever — but the gain does not
survive fusion.** dense is +0.023 with the CI clear of zero: a real
improvement in the component the embedder actually drives. Yet the hybrid arm —
what recall *ships* — moves only +0.0136, and its CI straddles zero. Fusing the
stronger dense ranking with the unchanged lexical half pulls the result back to
a statistical tie.

This is the 16 July report's own "strong first stage" thesis, seen from the
other side. That report argued reranking a strong dense stage doesn't help
because there's little room left to improve; here, *improving* the dense stage
doesn't help the hybrid output for the mirror-image reason — RRF averages the
sharper dense signal against a lexical half that didn't change, and dilutes the
gain. On a corpus where dense already leads (SciFact), a better dense model is
a better *dense-only* product, not obviously a better *hybrid* one.

## Speed: both prior claims were wrong

The 16 July report's summary called v2-MoE "stronger *and* ~5× faster on CPU."
Mid-experiment I "corrected" that to ~2× *slower*. **Clean measurement refutes
both.** Identical 200-doc workload (mean 1,496 chars), nothing else on the CPU,
model-load excluded by a warm-up pass:

| model | docs/min |
|---|---|
| nomic-embed-text (v1) | 63.3 |
| nomic-embed-text-v2-MoE | 60.5 |

**Comparable — ~4.5% apart, within noise.** The report's "5×" was real but
mis-transcribed: the source [17] compares v2-MoE against *1024-dim dense
models*, not against v1 (137M params, 768-dim). My "2× slower" was worse — it
came from a rate (27 chunks/min) measured while I was running the test suite,
mypy and ruff on the same 4 cores. CPU contention, not the model. Two wrong
speed numbers from two bad measurements, on the same afternoon, in a report
about the value of measuring. The correction is itself the lesson.

## What this means for recall

- **Not an unambiguous win.** On SciFact, v2-MoE is a significant *dense*
  improvement, a *hybrid* wash, and a speed wash. "Stronger and faster, drop-in"
  overstated it on all three counts.
- **Adopt it only if dense-leaning.** If recall moves toward dense-heavier
  fusion (the config default already leans 0.7/0.3 dense), the +0.023 dense gain
  starts to reach the shipped result and adoption is justified. Under balanced
  fusion on a lexical-friendly corpus, the case is weak.
- **One corpus is not the verdict.** SciFact is dense-favourable. NFCorpus
  (harder for dense) could show a different balance and is the obvious next run.
  This settles the *method* and the SciFact result; it does not settle
  "upgrade the default."
- **The prior report is corrected, not deleted.** Its Finding 3 and summary
  overclaimed; this file is the measured counterweight, and both are linked so
  the overclaim stays visible next to its refutation.

## A finding that outranks the bake-off: the BEIR numbers were measured on a confounded index

Setting up the arms surfaced something about recall's **published** BEIR
numbers. pg_search computes BM25 over the whole index; the `source` filter
restricts which rows return but not the corpus statistics used to score them
(verified directly: identical `paradedb.score` whether a query is scoped to one
source or three). The README's SciFact numbers were computed with scifact
sharing a database with NFCorpus **and** the author's personal notes **and** the
fixture — so the IDF that produced them was shaped by ~7,000 unrelated chunks.
BEIR assumes the index *is* the corpus.

The effect is visible: clean scifact-only lexical NDCG@10 is **0.6446**, the
mixed-index value was **0.6466**, and the README publishes **0.639**. Small
here, but it is a real methodological hole in the repo's most load-bearing
credibility claim (external, published-baseline-comparable numbers).

**Resolved 18 July 2026.** The README and `docs/design.md` BEIR tables were
regenerated on single-corpus indexes; see the "BEIR numbers regenerated on
single-corpus indexes" entry in the design decision log. The regeneration also
surfaced that the *old* shared index held stale document vectors (identical
text embedding to different vectors than current code), so the dense/hybrid
arms moved too — not from the confound (dense is composition-independent) but
from vector staleness. Both are fixed by single-corpus regeneration under
current code. Five of six published numbers went up.

## Reproduce

Dumps persisted at `~/beir_bakeoff/arm_v1.json`, `~/beir_bakeoff/arm_v2.json`
(per-query NDCG for all three arms, both models). The comparison uses
`eval.beir.per_query_scores` + `eval.metrics.paired_bootstrap_delta_ci`, both in
the repo and unit-tested. The bake-off runner itself was a throwaway; the
persisted per-query dumps are the artefact.
