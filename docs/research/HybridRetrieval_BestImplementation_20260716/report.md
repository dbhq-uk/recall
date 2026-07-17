# Best Implementation for Local-First Hybrid Retrieval over Notes and Code

**A state-of-the-art review, grounded in recall's own measurements**

*Mode: standard · Date: 16 July 2026 · Prepared for: recall (DBHQ Consulting Ltd)*

---

## Executive Summary

recall is a local-first hybrid retrieval server: dense vectors (`nomic-embed-text`) plus BM25, fused by Reciprocal Rank Fusion, over personal notes (prose) and code. During development, two empirical results on our golden query set surprised us and prompted this review:

1. **Equal-weight RRF (k=60) lost to dense-only retrieval.** Only a heavily dense-weighted convex combination barely edged out pure dense.
2. **Off-the-shelf cross-encoder reranking made retrieval worse**, not better — both a fast weak model (`ms-marco-MiniLM-L-6-v2`) and a strong slow one (`bge-reranker-base`) dropped MRR below the no-rerank hybrid and below dense-only.

Both findings ran against the received wisdom — and against recall's own design, which named the cross-encoder reranker as "the largest measured quality win available to us." This review asked whether we had made a mistake. **We had not.** The 2024–2026 information-retrieval literature confirms both results as known phenomena with well-understood mechanisms:

- Reranking a **strong** first-stage retriever with an **off-the-shelf, domain-mismatched** cross-encoder reliably produces diminishing or negative returns. The canonical "reranking is a big win" result assumes a *weak* (BM25) first stage. Multiple 2024–2026 papers state this directly ("Drowning in Documents"; "Multivector Reranking in the Era of Strong First-Stage Retrievers"; "When Reranking Hurts"). Anthropic's much-cited 67% failure-reduction used a *strong* reranker (Cohere) on a *hybrid* first stage with *contextual* chunks — a materially different setup from ours.
- Equal-weight RRF is a robust *zero-shot* default, not an optimum. It discards score magnitude and can only "dilute" a sharp signal from a strong single ranker. Weaviate moved its default off RRF to relative-score fusion (+6% recall); the 2025 "Dynamic Alpha Tuning" work shows many queries prefer *extreme* weights (pure dense or pure lexical) over any fixed blend.

The most valuable finding is what the evidence says recall should do **instead** of chasing reranking. The single highest-ROI change is an **embedder upgrade** — `nomic-embed-text` v1 sits roughly 5–8 MTEB points behind 2025–2026 leaders, and `nomic-embed-text-v2-MoE` is a drop-in replacement (identical asymmetric prefixes) that is both stronger and **~5× faster on CPU**. **[Corrected 17 July 2026 — this claim was tested and it overstated the case on both axes. On BEIR SciFact v2-MoE is a *significant dense* gain (+0.023 NDCG@10) but a *hybrid* wash and a *speed* wash (~4.5% slower, not 5× faster — the "5×" was vs 1024-dim models, not vs v1). See `../Recall_ReviewNextSteps_Research_20260717/bakeoff-results.md`.]** Second, recall's **heading-aware chunking already captures most of the gain** that Anthropic pays an LLM ~$1 per million tokens to generate — this is a genuine strength, not a gap. Third, fusion should move from naive equal-weight RRF toward normalized/relative-score fusion or the dense-leaning weighted combination recall already built, with per-query adaptive weighting as a research-grade frontier option.

The through-line: recall's instinct to **measure before shipping** is vindicated. The golden-query harness caught two features the field would have sold us on faith, one of which (reranking) would have degraded the product.

---

## Introduction

**Scope.** This report reviews best-practice and state-of-the-art (2023–2026) approaches to four levers in a local-first hybrid retrieval pipeline — fusion, reranking, embedding model, and chunking — and maps each back to recall's measured results and constraints (local-only, CPU-feasible, MIT-licensable, minimal dependencies, prose-first then code).

**Methodology.** Four parallel retrieval agents gathered citation-backed evidence, one per lever, from vendor engineering blogs (Anthropic, Weaviate, Qdrant, Elastic, OpenSearch, Pinecone, Jina, Snowflake, Nomic), the arXiv literature, and benchmark leaderboards (MTEB, BEIR). Findings were triangulated against recall's own golden-set measurements. Sources are listed in the Bibliography; the run manifest records the exact queries.

**Assumptions.** (a) recall's use pattern is top-10 retrieval feeding an agent's context, so metrics that reward top-of-list precision (MRR, Recall@10) matter most. (b) The query distribution is prose-question-heavy — natural-language questions over notes and code, not keyword lookups. (c) "Local by default" is a hard product constraint that excludes API rerankers/embedders from the default path.

---

## Finding 1 — Reranking a strong dense retriever with an off-the-shelf cross-encoder is a known failure mode

recall's measurement — MiniLM-L6 dropped MRR to 0.602 and bge-reranker-base to 0.638, both below the no-rerank hybrid (0.667) and dense-only (0.748) — is not an anomaly. It is a documented phenomenon with at least four converging mechanisms in the recent literature.

**First-stage strength inverts the value of reranking.** "Drowning in Documents: Consequences of Scaling Reranker Inference" states plainly that "reranking is competitive only on top of weak BM25 first stage, while strong dense retrievers often have rerankers hurt their performance unless the two signals are orthogonal" [1]. "Multivector Reranking in the Era of Strong First-Stage Retrievers" formalises the diminishing-returns curve: as the first stage improves, the marginal benefit of reranking shrinks toward zero, because the relevant documents are already ranked highly and there is little room left to improve — but ample room to *disturb* [2]. recall's first stage is `nomic-embed-text`, a strong 2024 dense model; it is precisely the regime where these papers predict reranking will not help.

**Reranking actively degrades high-confidence retrievals.** "When Reranking Hurts: Uncertainty-Based Gating for Few-Shot Reranking" finds that "for low-uncertainty instances, the baseline already retrieves highly relevant… contexts. Here, reranking can actually degrade performance" by overriding a stable, correct ordering with a topically-similar but worse one [3]. This matches recall's per-kind result, where reranking lowered MRR across *every* query kind — it was not rescuing hard queries, it was disturbing easy ones.

**Off-the-shelf MS-MARCO cross-encoders transfer poorly out of domain.** Both rerankers recall tested are trained on MS MARCO (web-passage relevance). SBERT's own documentation notes "notable performance drops" on several BEIR domains where "reranking does NOT improve performance" because the task needs in-domain knowledge the model lacks [4]. Practitioner guidance is explicit: "if [the] domain is legal contracts, medical records, or code, [a] generalist model might not rank content correctly; [a] fine-tuned cross-encoder offers highest quality" [5]. recall's domain — personal notes and source code — is exactly this out-of-domain case.

**Code and reasoning-intensive retrieval resist reranking entirely.** "Drowning in Documents" reports that for math and code, "no reranking method improved upon first-stage retrieval" [1]. recall's own SWE-bench result already hinted at this: on code issues, even hybrid fusion trailed dense-only.

**Why Anthropic's result is not a counter-example.** Anthropic's Contextual Retrieval reduced top-20 failures by 67% *with* reranking [6] — but the setup differs on every axis that matters: they reranked a **hybrid** (contextual-embeddings + contextual-BM25) first stage over a top-150 pool with a **strong commercial reranker (Cohere)**, not a weak MiniLM over a strong-dense pool. The evidence agent's synthesis is blunt: reranking helps "when first-stage signals are weak or orthogonal (e.g., dense + BM25 hybrid)" and with a strong reranker — not when a cheap generalist is bolted onto an already-strong dense retriever [3][5].

**Implication for recall.** Do not ship off-the-shelf reranking. If reranking is revisited, the literature prescribes: a **strong** reranker (jina-reranker-v3, mxbai-rerank-v2, or Cohere) not MiniLM; applied to the **hybrid** pool, not dense; **selectively** via uncertainty gating; over a **small** candidate set; and always measured against the golden set first. Note one wrinkle the evidence surfaced: a 2026 head-to-head found MiniLM-L6 *outperformed* the much larger bge-reranker on document reranking (0.870 vs 0.854 MAP) [7] — model size is not the lever, domain fit is. This is why "just use a bigger reranker" is not a reliable fix.

---

## Finding 2 — Equal-weight RRF is a robust default, not an optimum; on strong dense + conceptual queries it can lose

recall found equal-weight RRF (k=60) losing to dense-only. The literature both explains why and shows the field has moved beyond naive RRF.

**RRF discards score magnitude, which is where a strong ranker's signal lives.** RRF fuses on *rank position* alone — deliberately, to sidestep the score-scale incompatibility between unbounded BM25 and bounded cosine [8]. That robustness has a cost: when one ranker is confidently correct, RRF averages its sharp signal against a weaker ranker's noise. Kevin Tan's section-retrieval benchmark captures this exactly — BM25 scored MRR 0.93 against hybrid RRF's 0.63, with the memorable diagnosis that "there is nothing left for fusion to do except dilute" [9]. recall observed the mirror image: a strong *dense* ranker diluted by a noisy *lexical* half on prose queries.

**Vendors have moved their defaults off RRF.** Weaviate switched its default from RRF to relative-score fusion in v1.24, reporting ~6% recall improvement because normalized scores "retain more signal" than pure ranks [10]. OpenSearch's own benchmarks show RRF scoring 3.86% lower NDCG@10 than score-based methods across six datasets, trading quality for latency and calibration-free simplicity [11]. Qdrant offers Distribution-Based Score Fusion for exactly the heterogeneous-score case [12]. RRF remains the best *zero-shot, label-free* choice — but it is explicitly a floor, not a ceiling.

**Static blends are being replaced by per-query weighting.** The 2025 "Dynamic Alpha Tuning" paper is the most direct match to recall's situation: it finds "many queries benefit more from extreme values (pure BM25 or pure dense) rather than compromise," and its per-query learned alpha delivered a 7.5% Precision@1 gain over fixed α=0.5 on hybrid-sensitive queries [13]. This is precisely why recall's fixed weighting struggled — a semantic-heavy fixture wants near-pure-dense, while lexical queries want near-pure-lexical, and no single global weight serves both. Query-adaptive weighting (by length/type, or LLM-judged) is the 2025–2026 frontier [13][14].

**Implication for recall.** The weighted convex combination recall already built is the right *mechanism*. Options, in increasing sophistication: (a) keep RRF as the robust default but document that dense-only is competitive on conceptual loads; (b) add **relative-score / normalized fusion** as an alternative fusion mode (Weaviate's evidence suggests a few points of recall); (c) longer-term, **per-query adaptive weighting** — cheap heuristics first (short/identifier query → more lexical; long/natural-language query → more dense), learned or LLM-judged later. The k value should be low (10–20) for a top-10 use case, which recall already adopted [15].

---

## Finding 3 — The single highest-ROI change is the embedder, and it is a clean local upgrade

Across all four research threads, the dense retriever is the load-bearing component — so improving *it* is the lever with the most leverage, and here the evidence is unusually actionable.

**nomic-embed-text v1 is now behind the frontier.** v1 scores ~62.4 MTEB; 2025–2026 leaders sit 5–8 points higher [16]. Crucially, the upgrade path is nearly free of disruption: **`nomic-embed-text-v2-MoE`** uses the *same* `search_document:` / `search_query:` asymmetric prefixes recall already implements, achieves SOTA-competitive BEIR/MIRACL results with only 305M active parameters, and runs **~5× faster on CPU** than 1024-dim dense models [17][18]. For a local, CPU-only tool, "stronger *and* faster, drop-in" is the rare unambiguous win.

**BGE-M3 is a strategic alternative worth noting.** BGE-M3 produces dense, sparse (lexical), and multi-vector (ColBERT) representations from a *single* model [19]. For recall this is intriguing: it could **replace the separate BM25/pg_search stage** with in-model sparse weights, collapsing two subsystems into one and eliminating the ParadeDB dependency. Trade-offs: a larger model, ~31ms CPU latency for 1024-dim, and a significant architectural change. It is a v2 design question, not a v1 patch — but it directly addresses the "lexical half is noisy" problem by unifying the two signals in one trained model.

**Code needs its own consideration.** General embedders underperform on code; code-specific models (jina-code-embeddings, CodeXEmbed) beat them by 20%+ on code benchmarks [20][21]. recall is prose-first, so this is secondary — but if code retrieval becomes a priority, a per-source embedder (code files → a code embedder) is the evidence-backed path. Note this conflicts with recall's "one embedding model per database" invariant, so it would be a deliberate architectural change.

**Implication for recall.** Trial `nomic-embed-text-v2-MoE` against the golden set as the next quality experiment. It is local, Ollama-compatible, prefix-compatible, faster on CPU, and measurably stronger — the lowest-risk, highest-expected-value change available.

---

## Finding 4 — recall's heading-aware chunking is already a competitive quality lever

The chunking research delivered the most reassuring finding: recall's core design choice — parsing the heading structure and **prepending the heading trail into the embedded text** — is not a nice-to-have. It is, per the evidence, one of the largest quality levers available, and recall already has it.

**Contextual chunking is the biggest "free-ish" lever.** Anthropic's Contextual Retrieval — prepending an LLM-generated 50–100 token context to each chunk before embedding — cut top-20 retrieval failures by 35% (embeddings alone), 49% (with contextual BM25), and 67% (with reranking) [6]. But it costs ~$1.02 per million document tokens and requires an LLM in the ingestion path [6].

**Heading-aware chunking achieves comparable gains at zero cost.** An independent analysis reports that prepending markdown heading breadcrumbs yields ~49% failure reduction — matching contextual retrieval — while being *deterministic and free*, with no LLM call [22]. This is precisely recall's design. The hierarchical-chunking literature (HiChunk) independently converges on prepending heading hierarchy to chunks [23]. recall's prose chunking is, in effect, the cheap local version of the technique the field currently considers state-of-the-art.

**Other chunking levers are smaller or already present.** Semantic (embedding-based) chunking buys only 2–3% over fixed-size at high compute cost — "not justified" unless accuracy is paramount [24]. AST/function-boundary code chunking adds +4.3 Recall@5 on code [25] — and recall already does tree-sitter AST chunking. Late chunking (embed-whole-document-then-pool) is a moderate gain but needs a long-context embedder [26].

**Implication for recall.** This is a strength to protect and to *market*, not a gap to fill. The keep-it-passing test on the heading-trail-in-the-embedding is guarding a genuinely important property. An optional LLM-generated contextual layer could be a future add, but the deterministic heading trail already captures most of the value the field pays for.

---

## Synthesis & Insights

**The strongest pattern: recall is in the "strong first stage" regime, and that changes everything.** Most received RAG wisdom — "always rerank," "hybrid always beats both halves" — was established when the first stage was weak (BM25 or an early dense model). recall's first stage is a strong 2024 embedder over well-contextualised (heading-prepended) chunks. In that regime, the literature and recall's measurements agree: reranking's value collapses or inverts, and naive fusion can dilute rather than help. recall did not get unlucky; it built a good enough first stage that the usual second-stage tricks stopped paying off.

**The levers, ranked by evidence-backed ROI for recall specifically:**

1. **Embedder upgrade (`nomic-embed-text-v2-MoE`)** — stronger *and* faster on CPU, drop-in, local. Highest expected value, lowest risk. **[Corrected 17 July 2026: measured on SciFact it is a significant *dense* gain that does not survive fusion (hybrid wash) and is speed-comparable, not faster — not the unambiguous win claimed here. See `../Recall_ReviewNextSteps_Research_20260717/bakeoff-results.md`.]**
2. **Protect and promote heading-aware chunking** — already competitive with Anthropic's paid contextual retrieval; a differentiator.
3. **Better fusion (relative-score/normalized, or adaptive weighting)** — modest, worth the weighted mechanism recall already has; RRF is a floor.
4. **Reranking** — do *not* ship off-the-shelf; conditional at best, needs a strong reranker on a hybrid stage, selectively gated, and only if measured to help.
5. **Code-specific embedder / BGE-M3 unification** — real but architectural; v2 territory.

**The meta-insight: the golden harness is the product's most valuable asset.** Twice now, measurement has overruled both the design's own roadmap and the field's default advice. The reranker — the design's stated "largest quality win" — measurably degraded results. This is the honest-failure principle applied to recall's *own development*: don't ship what you can't measure a win from.

---

## Limitations & Caveats

- **recall's measurements are on a small, semantic-skewed fixture** (40 golden queries, ~650 chunks) plus a thin SWE-bench slice (8 instances, saturated Recall). They are directionally strong and now corroborated by the literature, but they are not large-sample proof. A `brain`-scale golden set would firm them up.
- **The reranking finding is specific to off-the-shelf, weak-to-mid cross-encoders.** It does not establish that *no* reranker could help — a domain-fine-tuned or top-tier reranker (Cohere, jina-v3) on the hybrid pool remains untested here, and the literature leaves that door open [3][6].
- **Vendor blogs carry vendor interest.** Weaviate's "relative-score fusion is better" and Nomic's "v2 is faster" are self-reported; treated as directional, corroborated where possible by independent sources.
- **Embedder-swap numbers are MTEB leaderboard deltas**, not recall-corpus measurements. The v2-MoE upgrade must be validated on recall's own golden set before adoption — the same discipline that produced these findings.
- **Standard-mode depth:** ~13 sources per thread, single triangulation pass. A deep/ultradeep run would add adversarial critique and a wider source pool.

---

## Recommendations

**Immediate (v1):**
1. **Do not build the cross-encoder reranker subsystem.** The measurement and the literature agree it does not help recall's regime. Record this decision and the evidence in the design doc, converting the roadmap's "reranker = biggest win" into "reranker = conditional, measured negative on our corpus."
2. **Ship the honest fusion story.** Keep the configurable weighted fusion; document that dense-only is competitive and that RRF is a robust floor, not an optimum. Default weighting stays a documented starting point, validated on a real corpus.
3. **Protect the heading-aware chunking** as a core, tested differentiator; say so in the README (it is the free local equivalent of contextual retrieval).

**Next quality experiment (highest ROI):**
4. **Trial `nomic-embed-text-v2-MoE`** against the golden set (it is Ollama-compatible, prefix-compatible, faster on CPU). This is the single most promising quality lever and fits every constraint. Requires a `reindex` (new model → new vectors), which recall already supports.

**Research-grade / v2:**
5. **Add relative-score / normalized fusion** as a selectable fusion mode; measure against RRF on the golden set.
6. **Prototype per-query adaptive weighting** with cheap heuristics (identifier/short → lexical-leaning; natural-language/long → dense-leaning) before anything learned.
7. **Evaluate BGE-M3** as a v2 architecture that unifies dense + sparse in one model and could retire the separate pg_search dependency.
8. **If reranking is ever revisited,** use a strong reranker on the *hybrid* pool with uncertainty gating, and gate the decision on a measured golden-set lift — never ship it on faith.

---

## Bibliography

1. Drowning in Documents: Consequences of Scaling Reranker Inference — https://arxiv.org/pdf/2411.11767
2. Multivector Reranking in the Era of Strong First-Stage Retrievers — https://arxiv.org/pdf/2601.05200
3. When Reranking Hurts: Uncertainty-Based Gating for Few-Shot Reranking — https://arxiv.org/html/2606.31087v1
4. SBERT MS MARCO Cross-Encoder documentation — https://sbert.net/examples/cross_encoder/training/ms_marco/README.html
5. Reranking in RAG: Cross-Encoders, Cohere Rerank & FlashRank — https://medium.com/@vaibhav-p-dixit/reranking-in-rag-cross-encoders-cohere-rerank-flashrank-c7d40c685f6a
6. Anthropic — Introducing Contextual Retrieval — https://www.anthropic.com/engineering/contextual-retrieval
7. Best Reranker Models for RAG: Open-Source vs API (2026) — https://docs.bswen.com/blog/2026-02-25-best-reranker-models/
8. Chauzov — Hybrid Retrieval & RRF Score Normalization — https://avchauzov.github.io/blog/2025/hybrid-retrieval-rrf-rank-fusion/
9. Kevin Tan — BM25 vs Hybrid Search in Section RAG — https://blog.jztan.com/bm25-vs-hybrid-search-section-rag/
10. Weaviate — Hybrid Search Fusion Algorithms — https://weaviate.io/blog/hybrid-search-fusion-algorithms
11. OpenSearch — Introducing Reciprocal Rank Fusion for Hybrid Search — https://opensearch.org/blog/introducing-reciprocal-rank-fusion-hybrid-search/
12. Qdrant — Hybrid Search Essentials (DBSF) — https://qdrant.tech/course/essentials/day-3/hybrid-search/
13. DAT: Dynamic Alpha Tuning for Hybrid Retrieval — https://arxiv.org/html/2503.23013v1
14. Particula — Hybrid Embeddings: Dense + Sparse Tuning Guide — https://particula.tech/blog/hybrid-embeddings-dense-sparse-search
15. Elastic — Weighted Reciprocal Rank Fusion — https://www.elastic.co/search-labs/blog/weighted-reciprocal-rank-fusion-rrf
16. Nomic Embed: Training a Reproducible Long-Context Text Embedder — https://arxiv.org/pdf/2402.01613
17. Nomic — Training Sparse Mixture-of-Experts Text Embedding Models (v2-MoE) — https://static.nomic.ai/nomic_embed_multilingual_preprint.pdf
18. nomic-ai/nomic-embed-text-v2-moe (model card) — https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe
19. BGE-M3: Dense, Sparse & Multi-Vector in one model — https://pristren.com/blog/bge-m3-embeddings-multilingual/
20. Jina Code Embeddings: SOTA Code Retrieval at 0.5B and 1.5B — https://jina.ai/news/jina-code-embeddings-sota-code-retrieval-at-0-5b-and-1-5b/
21. CodeXEmbed: A Generalist Embedding Model Family for Code Retrieval — https://arxiv.org/pdf/2411.12644
22. Free Contextual Chunk Headers: Heading-Aware Chunking for Hybrid Retrieval — https://dev.to/kartikeyraj/free-contextual-chunk-headers-heading-aware-chunking-for-hybrid-retrieval-560
23. HiChunk: Hierarchical Chunking with Adaptive Merging — https://arxiv.org/pdf/2509.11552
24. Firecrawl — Best Chunking Strategies for RAG (2026) — https://www.firecrawl.dev/blog/best-chunking-strategies-rag
25. cAST: Structural Chunking via AST — https://aclanthology.org/2025.findings-emnlp.430.pdf
26. Late Chunking (Jina AI) — https://arxiv.org/pdf/2409.04701
27. From BM25 to Corrective RAG (reranking lift on financial docs) — https://arxiv.org/pdf/2604.01733
28. jina-reranker-v3: Listwise Document Reranking — https://arxiv.org/pdf/2509.25085
29. Qwen3 Embedding — https://qwenlm.github.io/blog/qwen3-embedding/
30. Snowflake Arctic-Embed 2.0 — https://www.snowflake.com/en/engineering-blog/snowflake-arctic-embed-2-multilingual/

## Methodology Appendix

- **Run mode:** standard (6-phase pipeline).
- **Output path:** `docs/research/HybridRetrieval_BestImplementation_20260716/` (resolved via git root).
- **Evidence gathering:** four parallel retrieval agents (haiku), one per lever (reranking-when-it-helps; fusion methods & tuning; local embedders for prose+code; chunking & contextual retrieval), each returning structured `CLAIM | SOURCE | URL | evidence` findings.
- **Triangulation:** each recall measurement (RRF-loses-to-dense; reranking-degrades) was checked against independent sources; both were corroborated by ≥3 cluster-independent sources.
- **Grounding:** recall's own golden-set numbers (fixture: dense MRR 0.748, hybrid 0.667, +MiniLM 0.602, +bge 0.638) are the anchor the external evidence was tested against.
- **Known bias controls:** vendor self-reported numbers flagged as directional; leaderboard deltas flagged as not-yet-validated on recall's corpus.
