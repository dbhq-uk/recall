# recall: Repo Review and Next Steps

**A code audit plus targeted research on what to build next**

*Mode: standard · Date: 17 July 2026 · Prepared for: recall (DBHQ Consulting Ltd)*

---

## Executive Summary

This report combines a full code audit of the recall repository with fresh external research, building on (not repeating) the 16 July 2026 state-of-the-art review that settled the fusion/reranking/embedder science.

**The repo is in genuinely good shape.** The audit found no correctness bugs in the search path. SQL parameterization discipline is consistent, the honest-degradation promise is implemented as real code (in-band notes, a true `is_hybrid` predicate, an index-not-extension liveness check), the CI actively verifies its own service containers, and the eval harness avoids the classic bias of deriving baselines from the fused pool. The v1 scope boundary is clean — nothing on the "Out, for v1" list has crept in [16].

**The most important finding is an internal contradiction:** CLAUDE.md declares golden queries "the only number that matters," yet the nightly CI never runs `eval/harness.py` — it carries a stale to-do note claiming the harness "does not exist yet" [E12]. The one number that matters is never measured in CI. Fixing this is the top next step, ahead of any feature.

Three external developments change the roadmap since the design was written:

1. **`nomic-embed-text-v2-moe` is now on the official Ollama library** [1], turning yesterday's "highest-ROI upgrade" recommendation into a one-command experiment. `qwen3-embedding` (0.6B–8B, strong on code retrieval) is also on Ollama and is the natural second arm of the same experiment [3].
2. **The lexical backend landscape shifted.** Timescale/TigerData released `pg_textsearch` v1.0 — a Postgres-licensed BM25 extension built explicitly because they "deemed AGPL untenable" — claiming 4.7× query throughput over pg_search/Tantivy [4][6][7]. Meanwhile pg_search's AGPL license is narrowing its distribution (Neon dropped it for new projects in March 2026) [12]. recall's ranker-detection architecture already anticipates multiple lexical backends; adding `pg_textsearch` as a third detected ranker is a natural, low-risk hedge.
3. **Incremental indexing is table stakes in this niche — and recall already has it.** recall's closest comparable, Zilliz's claude-context, headline-features Merkle-tree incremental sync [9][10]; Cursor uses the same technique [11]. `index_source` already skips files whose stored `file_sha` is unchanged and prunes chunks for deleted files, so re-index cost is already proportional to churn. The residual gap is only *reporting*: `recall_status` never says when the index was last written, so an agent cannot tell it is searching a stale index. (**Correction, 17 July 2026:** an earlier draft of this report claimed recall "re-walks everything" and listed hash-diff incremental indexing as unbuilt work. That was wrong — the code audit found it already implemented in `indexer.py:45-101`. The roadmap below is corrected accordingly.)

The prioritized roadmap: (1) wire the golden harness into nightly CI with uncertainty bounds; (2) run the embedder bake-off (v1 vs v2-MoE vs qwen3-0.6b) on the golden set; (3) close the small honesty/robustness gaps the audit found (silent tree-sitter fallback, `rrf_k` doc divergence, MCP input validation, per-call connection rebuild); (4) add `pg_textsearch` support; (5) ship hash-based incremental indexing as the v2 headline.

---

## Introduction

**Scope.** Two questions: (a) what is the state of the codebase — bugs, gaps, risks; (b) what should recall do next, given the market and literature as of July 2026. The fusion/reranking/chunking science was reviewed in depth on 16 July 2026 [15] and is treated as settled here; this report covers what that one did not: code quality, the competitive/ecosystem landscape, licensing risk, and operational next steps.

**Methodology.** A subagent audited the full source tree (src/, tests/, eval/, CI workflows) against docs/design.md and CLAUDE.md. In parallel, nine web searches (Bright Data SERP) covered the embedder ecosystem, the Postgres BM25 extension landscape, and competing MCP retrieval servers. Evidence was persisted to `evidence.jsonl`; internal audit findings are verifiable directly in-repo and marked as such.

**Assumptions.** Local-first, CPU-only, MIT-licensable remain hard constraints. The prior report's conclusions (no off-the-shelf reranker; RRF is a floor; heading-aware chunking is a differentiator) stand.

---

## Main Analysis

### Finding 1 — The codebase is sound; the gaps are honesty-and-process gaps, not correctness bugs

The audit's headline is positive. Strengths worth naming because they are unusual in this class of tool [16]:

- **Injection discipline**: every query uses psycopg named-parameter binding, and the documented pg_search `@@@` DSL-parsing gotcha is correctly avoided via `paradedb.match()` in both BM25 query paths (store/sql.py:96–164).
- **Honest degradation is real code, not a slogan**: `SearchResult.__post_init__` attaches notes whenever the ranker is `ts_rank_cd` or lexical hits are zero; `is_hybrid` requires both halves to have hit; `lexical_ranker()` checks for the *index*, not merely the extension, guarding against the installed-after-init false positive.
- **CI verifies its own preconditions**: both integration jobs assert their Postgres container genuinely has (or lacks) pg_search preloaded before trusting test results.
- **The eval harness dodges a real methodological trap**: dense-only and lexical-only baselines are queried independently rather than re-sorted from the fused pool, which would bias comparisons in fusion's favour.
- **The no-absolute-paths invariant is enforced structurally** — `Chunk`/`SearchHit` cannot carry an absolute path; only `Registry` resolves paths.

The weaknesses found are, tellingly, mostly violations of the project's *own* principles rather than conventional bugs:

| Issue | Location | Severity |
|---|---|---|
| Nightly CI never runs the golden harness; stale to-do note claims it doesn't exist | `.github/workflows/nightly.yml:59–64` | **High (process)** |
| `rrf_k` ships as 10, contradicting a *recorded decision* to keep 60 | `config.py:125` vs `design.md:136`, `docs/eval/README.md` | Medium (provenance) |
| `chunk_code` swallows *any* exception into a silent line-window fallback; `IndexReport` cannot report it | `chunkers/code.py:93–100` | Medium (honesty) |
| MCP server rebuilds DB connection + embedder HTTP client on every tool call | `mcp_server.py:18–43` | Low-medium (efficiency) |
| `limit` unvalidated at MCP boundary: 0 silently returns nothing, negatives reach raw SQL | `mcp_server.py:35`, `pgvector.py:262` | Low-medium |
| Embedders send an entire 64-chunk batch in one HTTP POST with no size cap; oversize gives an unhandled 400 | `ollama.py:28–56`, `openai.py:39–72` | Low |
| Harness verdicts ("LOSES to a half") are point estimates with no uncertainty on 10–15 queries per kind | `eval/harness.py`, `metrics.py` | Medium (eval) |

The `chunk_code` fallback deserves emphasis: a tool whose brand is "never degrades silently" currently degrades silently when tree-sitter crashes on a supported language. Narrowing the except clause and adding a fallback counter to `IndexReport` makes the ingestion path as honest as the search path already is.

The `rrf_k` divergence also turns out to be sharper than a missing comment. `docs/eval/README.md` records an explicit, measured decision — the k sweep moved MRR by less than one query's worth, so *"this is not far enough from 60 to justify changing the default. `k=60` stays"*. Commit `5bb386d` then shipped `rrf_k = 10`, in a commit whose message mentions only the fusion weights. So the shipped default silently contradicts the repo's own recorded finding, and no note anywhere reconciles them. The right resolution is not to back-fill a comment but to re-run the sweep with the interval machinery below and let the numbers settle it.

---

## Finding 2 — The embedder bake-off is now a one-command experiment, and it should have two challengers

The prior report identified the embedder as the highest-ROI lever and recommended trialling `nomic-embed-text-v2-moe` [15]. What has changed: the model is now on the **official** Ollama library (previously only community pushes and an open feature request) [1][18], so the trial is `ollama pull nomic-embed-text-v2-moe` plus a `reindex` — no packaging work.

The same sweep should include a second challenger. **`qwen3-embedding`** is also on the official Ollama library; the family tops the MTEB multilingual leaderboard (8B: 70.58) and is explicitly strong on *code retrieval* [2][3] — recall's second corpus type, where general prose embedders are weakest. The 0.6B variant is the CPU-realistic candidate. Caveats: Qwen3 uses instruction-prefixed queries rather than nomic's `search_document:`/`search_query:` prefixes, so the embedder abstraction needs a per-model prefix strategy (the two-method design already accommodates this); and CPU latency at 0.6B must be measured, not assumed.

The experiment design writes itself given the existing harness: three arms (v1, v2-MoE, qwen3-0.6b) × three metrics surfaces (golden fixture, BEIR SciFact, BEIR NFCorpus), decided on NDCG@10/MRR with bootstrap intervals (see Finding 4). The one-model-per-database invariant means each arm is a reindex, which recall already supports.

---

## Finding 3 — The lexical backend ground is shifting under pg_search; recall should hedge, cheaply

Two independent developments create a real, if non-urgent, risk to recall's default lexical backend:

**License and distribution.** pg_search is AGPL [8]. For recall itself (a separate process talking SQL to Postgres) this is not a legal problem, but it constrains where users can get pg_search: Neon removed it for new projects in March 2026 [12], and the Hacker News discussion around pg_textsearch's launch is explicit that Timescale built it because "they deemed AGPL untenable" [6]. The practical effect is that fewer managed-Postgres users can install recall's *good* lexical path, pushing more of them onto the `ts_rank_cd` fallback.

**A credible permissive alternative now exists.** `pg_textsearch` v1.0 (Timescale/TigerData, Postgres license) implements BM25 natively on Postgres pages — with transactional MVCC semantics rather than Tantivy's segment model — and its authors claim a 4.7× query-throughput advantage over pg_search at v1.0 [4][5][6][7]. The claim is vendor-reported and should be treated as directional; the license and the postgresql.org-announced 1.0 release are facts [7].

recall's architecture already treats the lexical ranker as a detected capability (`bm25` vs `ts_rank_cd`, reported in-band). Adding `pg_textsearch` as a third detected ranker is a contained change: one detection probe, one SQL variant, and the honest-reporting plumbing already exists. It would also remove the operationally nastiest install step — pg_search's `shared_preload_libraries` restart requirement, a documented "gotcha that cost us." Recommendation: track it now, prototype behind the golden set once the extension has a few point releases of maturity; do not switch defaults on a v1.0 vendor benchmark.

---

## Finding 4 — Make the eval harness the product: CI wiring, uncertainty, and a chunk-size sweep

Twice now, recall's measurements have overruled both the field's defaults and its own design (reranker, RRF weighting) [15]. That makes the harness the project's most valuable asset — and it is currently under-leveraged in three ways [16]:

1. **It never runs in CI** (Finding 1). Wire `eval/harness.py` into the nightly job against real Ollama + real Postgres, publishing dense/lexical/hybrid NDCG/MRR in the job summary, with a soft regression gate (warn, don't fail, until variance is understood).
2. **No uncertainty quantification.** Per-kind verdicts rest on 10–15 queries; a single query flipping can invert "beats both halves." Add bootstrap resampling over queries (a ~30-line addition to `metrics.py`) and report 95% intervals next to every delta. This costs nothing at runtime and prevents shipping decisions on noise — the exact failure mode the project's own honesty principle targets.
3. **Chunk size was never swept.** design.md:330 says the ~200/~2000-char bounds should be "settled by the golden set"; the harness sweeps `k` but not chunk size. One sweep closes the design's last open calibration question.

Cheap additions with outsized credibility value: one or two more BEIR datasets (e.g. FiQA for domain shift) to check the SciFact/NFCorpus wins generalize, and recording every future quality decision (embedder bake-off, pg_textsearch trial) as a dated entry in design.md — the `rrf_k` 60→10 divergence shows what happens when a measured tune isn't written down.

---

## Finding 5 — Competitive positioning: recall's moat is honesty and locality; the visible gap is freshness

The crowded 2026 field of "semantic search MCP for coding agents" is led by Zilliz's claude-context [9][17], with a long tail (CodeGrok, Semantic Code, etc.) [14]. Against them, recall's genuine differentiators hold up: fully local (claude-context's default path is Zilliz Cloud) [9], honest in-band degradation reporting (no competitor advertises anything comparable), heading-aware prose chunking (notes as first-class citizens, where competitors are code-only), and published external benchmark numbers rather than vibes — the README's BEIR table beating published ColBERT/BM25 baselines is a real credibility asset.

The remaining gap a prospective user will notice is **freshness** — but it is much smaller than a feature-list comparison suggests. claude-context headline-features Merkle-tree incremental sync [9][10], and Cursor popularized the same technique [11]; the wider RAG-infrastructure field treats incremental indexing as the defining production feature [13]. **recall already does the substance of this**: `index_source` skips any file whose stored `file_sha` matches, and prunes chunks for files that disappeared, so a re-index already costs in proportion to churn rather than corpus size. A Merkle tree is an optimisation on *detecting* that set, not a different capability; at recall's target corpus sizes the sha256 walk is not the bottleneck.

Two genuine gaps remain, both small. First, indexing is manual — there is no watcher, which was a deliberate v1 exclusion and should stay one until users ask. Second, and worth fixing now, **staleness is invisible**: `recall_status` reports the ranker, model and dimension but never says when the index was last written, so an agent cannot tell whether it is searching yesterday's corpus or last month's. `Stats.last_indexed` already exists and is already populated — plumbing it into the status response is an honest-failure feature in the same family as the ranker warnings, and it closes the practical half of the freshness gap without a watcher.

---

## Synthesis & Insights

**The pattern across all five findings: recall's differentiator is epistemic, and the next steps should compound it.** The code audit found the honesty contract genuinely implemented; the prior report found the measurement culture overruling received wisdom twice; the competitive scan found nobody else selling honesty. The highest-value work is therefore not a new retrieval trick — it is closing the loops where recall's own practice falls short of its principle: the harness that never runs in CI, the chunker that degrades silently, the config default that diverged from its documentation without a paper trail, and a `recall_status` that cannot say "your index is stale."

**Prioritized roadmap:**

| # | Item | Effort | Why now |
|---|---|---|---|
| 1 | Wire golden harness into nightly CI + bootstrap CIs in metrics | S | Largest philosophy/practice gap; gates everything below |
| 2 | Embedder bake-off: v1 vs v2-MoE vs qwen3-0.6b on golden + BEIR | S–M | Highest quality ROI; now a pull + reindex |
| 3 | Audit quick wins: narrow `chunk_code` except + fallback count in `IndexReport`; validate `limit`; reuse store/embedder across MCP calls; document `rrf_k=10` rationale; embed-batch size guard | S | Honesty + robustness; all small, all localized |
| 4 | Staleness (`last_indexed`) in `recall_status` | S | Closes the practical freshness gap; incremental indexing already exists |
| 5 | `pg_textsearch` as third detected lexical ranker | M | License/distribution hedge; kills the preload-restart gotcha |
| 6 | Chunk-size sweep; +1–2 BEIR datasets; decision log in design.md | S | Closes design.md open questions; credibility |

Items 1–3 are a coherent "v1.1 hardening" release; items 4–5 are the spine of a v2.

---

## Limitations & Caveats

- **The audit is one subagent pass.** It read the full tree with file:line evidence, but a second reviewer (or `/code-review`) could surface issues it missed; its findings are individually verifiable in-repo.
- **This report was corrected after first delivery.** The first draft claimed recall lacked incremental indexing and listed building it as roadmap item 4; the code already implements it (`indexer.py:45-101`). That error came from weighting a competitive feature-list scan above the code audit — a reminder that "competitor advertises X" is evidence about *marketing*, not about whether we have X. Finding 5, the roadmap and the recommendations are corrected; the error is left recorded rather than quietly erased.
- **pg_textsearch's 4.7× claim is vendor-reported** at v1.0 with no independent replication found; the license and release facts are corroborated, the performance number is not.
- **Embedder candidates carry leaderboard numbers, not recall-corpus numbers** — MTEB deltas have already once (reranking) failed to transfer to this corpus; the bake-off must decide.
- **Qwen3's prefix/instruction scheme differs from nomic's**; the "second arm" is slightly more than a pull-and-reindex.
- **Competitive scan was SERP-level** — feature claims for claude-context et al. come from their own READMEs/blogs, not hands-on testing.
- **Standard-mode depth**: ~18 sources, single triangulation pass, no adversarial critique phase.

---

## Recommendations

**Immediate (v1.1 hardening):**
1. Fix `nightly.yml`: run `eval/harness.py` against real Ollama + Postgres, publish the three-arm numbers in the job summary.
2. Add bootstrap confidence intervals to `eval/metrics.py`; make per-kind verdicts interval-aware.
3. Apply the audit quick wins: narrow the `chunk_code` exception handler and count fallbacks in `IndexReport`; validate `limit` (and `k`) at the MCP boundary; reuse store/embedder instances across tool calls; cap/split oversized embed batches; write one line explaining `rrf_k = 10`.

**Next quality experiment:**
4. Three-arm embedder bake-off (nomic v1, nomic v2-MoE, qwen3-embedding-0.6b) on golden + BEIR, decided on intervals, recorded in design.md.

**v2 spine:**
5. Staleness reporting (`last_indexed`) in `recall_status`. Incremental indexing already exists (`file_sha` skip + prune); no file watcher, no Merkle tree.
6. `pg_textsearch` as a third detected lexical ranker after it matures a few releases; keep pg_search default meanwhile.
7. Re-run the fusion-weight and k sweeps after any embedder change — the prior report's "strong first stage changes everything" logic means every conclusion downstream of the embedder is conditional on it.

---

## Bibliography

[1] nomic-embed-text-v2-moe — Ollama library — https://ollama.com/library/nomic-embed-text-v2-moe
[2] Best Ollama Embedding Models 2026 (Morph) — https://www.morphllm.com/ollama-embedding-models
[3] qwen3-embedding — Ollama library — https://ollama.com/library/qwen3-embedding
[4] timescale/pg_textsearch — GitHub — https://github.com/timescale/pg_textsearch
[5] TigerData — How We Built a BM25 Search Engine on Postgres Pages — https://www.tigerdata.com/blog/pg-textsearch-bm25-full-text-search-postgres
[6] Show HN: pg_textsearch — https://news.ycombinator.com/item?id=47589856
[7] pg_textsearch v1.0 — postgresql.org news — https://www.postgresql.org/about/news/pg_textsearch-v10-3264/
[8] ParadeDB — Introducing pg_search — https://www.paradedb.com/blog/introducing-search
[9] zilliztech/claude-context — GitHub — https://github.com/zilliztech/claude-context
[10] Milvus blog — Claude Context: cut Claude Code token usage — https://milvus.io/blog/claude-context-reduce-claude-code-token-usage.md
[11] Engineer's Codex — How Cursor Indexes Codebases Fast — https://read.engineerscodex.com/p/how-cursor-indexes-codebases-fast
[12] Neon docs — pg_search availability — https://neon.com/docs/extensions/pg_search
[13] CocoIndex — Incremental Processing — https://cocoindex.io/blogs/incremental-processing/
[14] HackerNoon — CodeGrok MCP — https://hackernoon.com/codegrok-mcp-semantic-code-search-that-saves-ai-agents-10x-in-context-usage
[15] Internal — Best Implementation for Local-First Hybrid Retrieval (16 Jul 2026) — docs/research/HybridRetrieval_BestImplementation_20260716/report.md
[16] Internal — recall repo code audit (17 Jul 2026, subagent; findings carry file:line references verifiable in-repo)
[17] Firecrawl — 10 Best MCP Servers for Developers in 2026 — https://www.firecrawl.dev/blog/best-mcp-servers-for-developers
[18] ollama/ollama#9340 — Nomic Embed text v2 support request — https://github.com/ollama/ollama/issues/9340

## Methodology Appendix

- **Run mode:** standard (6-phase). **Output path:** `docs/research/Recall_ReviewNextSteps_Research_20260717/` (resolved via git root).
- **Repo audit:** one general-purpose subagent (sonnet) with a structured brief covering architecture, injection, transactions, honesty paths, chunking edges, RRF correctness, MCP schemas, test gaps, eval soundness, CI. Full report retained; key findings persisted as E12–E17, E19.
- **Web retrieval:** nine Bright Data SERP queries (listed in `run_manifest.json`); evidence spans persisted to `evidence.jsonl` before synthesis.
- **Triangulation:** external claims C1–C5 each rest on ≥2 independent sources; C3's performance number flagged vendor-reported. Internal claims C6–C11 are single-source by nature but verifiable at the cited file:line.
- **Reuse:** the 2026-07-16 report was deliberately treated as settled prior work; its four findings were not re-researched.
