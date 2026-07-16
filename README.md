<div align="center">

<img src="assets/logo/recall-hero.png" alt="Lexical results and dense-vector nodes streaming into a single azure fusion point" width="880">

<br><br>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo/recall-wordmark-dark.png">
  <img alt="recall" src="assets/logo/recall-wordmark-light.png" width="300">
</picture>

<br>

**Hybrid BM25 + vector retrieval for coding agents, spoken over MCP.**

Local-first &nbsp;·&nbsp; tag-addressed corpora &nbsp;·&nbsp; honest about every degradation

<br>

[![License: MIT](https://img.shields.io/badge/License-MIT-2E9BFF?style=flat-square)](LICENSE)
&nbsp;![Python](https://img.shields.io/badge/Python-3.12+-46566E?style=flat-square&logo=python&logoColor=white)
&nbsp;![Protocol: MCP](https://img.shields.io/badge/protocol-MCP-2E9BFF?style=flat-square)
&nbsp;![Retrieval: BM25 + vectors, RRF](https://img.shields.io/badge/retrieval-BM25%20%2B%20vectors%20(RRF)-46566E?style=flat-square)
&nbsp;![Status: v1](https://img.shields.io/badge/status-v1-2E9BFF?style=flat-square)

</div>

---

## What recall is

recall is a local-first hybrid retrieval server. It indexes your notes and
your code, searches them with **BM25 and dense vectors fused by Reciprocal
Rank Fusion**, and returns ranked passages to your coding agent over MCP.

It is built for prose first: markdown gets heading-aware chunking that
carries its heading trail into the embedding, so notes are not a second-class
citizen bolted onto a code tool.

**What it is not:** lexical search over code is already excellent in every
agent harness — recall is not trying to out-grep grep. It is for the queries
grep cannot serve: the ones where you do not know the words you are looking
for. It is not a cloud service (there is no hosted component and no
telemetry), and it is not a general RAG framework — it does retrieval, and it
does not chunk PDFs, call LLMs, or manage prompts.

Its defining promise: **it never degrades silently.** If the real BM25
ranker is missing, or the lexical half of a query returns nothing, recall
says so in the response. A hybrid search that has quietly become a
dense-only search is worse than useless, because it looks like it is
working.

## The measured results

We evaluated recall against [BEIR](https://github.com/beir-cellar/beir), the
standard information-retrieval benchmark, using BEIR's own published
baselines. These are external, un-authored corpora and query sets — nobody
here wrote the questions or the relevance labels.

**BEIR SciFact** (5,183 documents, 300 expert-labelled queries), NDCG@10:

| system | NDCG@10 |
|---|---:|
| **recall (hybrid)** | **0.711** |
| recall (dense only) | 0.700 |
| ColBERT (published) | 0.671 |
| BM25 (published) | 0.665 |
| TAS-B (published) | 0.643 |
| recall (lexical only) | 0.639 |
| ANCE (published) | 0.507 |
| DPR (published) | 0.318 |

**BEIR NFCorpus** (3,633 documents, 323 queries), NDCG@10:

| system | NDCG@10 |
|---|---:|
| **recall (hybrid)** | **0.339** |
| BM25 (published) | 0.325 |
| recall (dense only) | 0.320 |
| TAS-B (published) | 0.319 |
| ColBERT (published) | 0.305 |
| recall (lexical only) | 0.303 |
| ANCE (published) | 0.237 |
| DPR (published) | 0.189 |

**Fusion beats both halves on both datasets** — SciFact 0.711 > 0.700 >
0.639, NFCorpus 0.339 > 0.320 > 0.303 — and recall's hybrid beats the
published BM25 baseline on both (+0.046 on SciFact, +0.014 on NFCorpus).

Two honest caveats:

- BEIR documents are short abstracts (about 1.1 chunks per document), so
  this validates recall's **ranking and fusion**, not its chunking. Chunking
  quality is a separate, harder-to-benchmark question.
- Our lexical arm lands within −0.026 (SciFact) / −0.022 (NFCorpus) of
  published BM25 — inside the ±0.05 band that Kamalloo et al. (SIGIR 2024)
  attribute to ordinary index-configuration differences. In other words, our
  BM25 reproduces the reference implementation; it is not a weaker imitation
  of it.

## Setup

**Postgres + [`pgvector`](https://github.com/pgvector/pgvector)** for dense
search. Optional [ParadeDB `pg_search`](https://github.com/paradedb/paradedb)
for real BM25 — it requires `shared_preload_libraries = 'pg_search'` **and a
genuine Postgres restart** to take effect. Without it, recall falls back to
Postgres's built-in `ts_rank_cd` and says so, loudly, everywhere it matters
(`recall doctor`, `recall_status`, and every `recall_search` response).

**[Ollama](https://ollama.com)** running `nomic-embed-text` (768-dim) is the
default embedder, entirely local. An OpenAI embedder is also supported for
anyone who wants it — and it warns, every time it is used, that content
leaves the machine.

```bash
uv sync
export RECALL_DATABASE_URL="postgresql://recall@localhost:5432/recall"

recall init                    # creates the schema; fixes the embedding model for this DB's life
recall register /path/to/notes # reads that source's .recall.toml, learns its tag
recall index brain             # walks, chunks, embeds, upserts
recall doctor                  # confirms which lexical ranker is ACTUALLY live
recall serve --source brain    # runs the MCP server over stdio
```

CLI surface: `recall init`, `register <path>`, `index <tag>`, `reindex
<tag>`, `sources`, `doctor`, `serve`.

A `.recall.toml` at the root of a source declares its tag and is committed,
so it travels with the source through git:

```toml
[source]
tag = "brain"
include = ["**/*.md"]
exclude = ["**/node_modules/**", "**/.git/**"]
```

`~/.config/recall/registry.toml` is the machine-local map from tag to local
path, written by `recall register <path>`:

```toml
[sources.brain]
path = "/home/devops/brain"
```

**An index is addressed by tag, never by path, so it survives moving
machines.** Every chunk is identified by `{tag}:{rel_path}:{chunk_idx}` —
never by an absolute path — and paths are resolved back to absolute only at
read time, through the registry, on the machine doing the reading.

## The honest-failure promise

This is the product, not a footnote.

- `recall doctor` reports which lexical ranker is *actually* live —
  `bm25` (ParadeDB `pg_search`, genuinely present) or `ts_rank_cd` (the
  fallback) — and warns loudly when it is the fallback, explaining exactly
  what that costs (no term-frequency saturation, no document-length
  normalisation) and how to fix it.
- Every `recall_search` response carries a `retrieval` block alongside the
  results: the live lexical ranker, whether both halves actually
  contributed hits, the fusion policy in force (`rrf_k`, `weight_dense`,
  `weight_lexical`), and any degradation notes. **A dense-only result is
  never presented as hybrid.**

## MCP wiring

```json
{
  "mcpServers": {
    "recall": { "command": "uvx", "args": ["recall", "serve", "--source", "brain"] }
  }
}
```

Three tools are exposed: `recall_search(query, sources=None, limit=10)`,
`recall_sources()` (tag, chunk count, last indexed, per source), and
`recall_status()` (which lexical ranker, embedding model, dimension and
backend are live right now). Indexing is deliberately **not** an MCP tool —
it is slow and mutating, so it stays a CLI command an agent cannot trigger
mid-conversation.

## What we measured and changed our mind about

- **Cross-encoder reranking made retrieval worse on our corpus, not
  better.** We measured two off-the-shelf rerankers
  (`ms-marco-MiniLM-L-6-v2` and `bge-reranker-base`) against the no-rerank
  hybrid baseline, and both *lowered* MRR. This matches the recent
  literature: reranking reliably helps a *weak* first-stage retriever (the
  classic BM25-then-rerank pipeline); recall's first stage is already a
  strong 2024 dense model, and bolting a domain-mismatched cross-encoder
  onto a strong retriever tends to add noise, not signal. So v1 ships **no
  reranker**, contrary to the original roadmap. See
  [`docs/research/`](docs/research/) for the full write-up and citations.
- **Fusion weighting is configurable** (`weight_dense` / `weight_lexical` /
  `rrf_k`, via `~/.config/recall/config.toml` or `RECALL_FUSION_WEIGHT_DENSE`
  / `RECALL_FUSION_WEIGHT_LEXICAL` / `RECALL_RRF_K`), because equal-weight
  RRF is a robust default, not an optimum — the literature and our own
  measurements both show query mixes where a fixed 50/50 blend leaves
  performance on the table.
- Our RRF implementation is **verified against [`ranx`](https://github.com/AmenRa/ranx)'s
  reference implementation** (identical ordering and scores) — see
  `tests/test_metrics.py`.

## v1 scope

**In:** pgvector backend, Ollama and OpenAI embedders, markdown
(heading-aware) and code (tree-sitter) chunkers, RRF fusion with an honest
`ts_rank_cd` fallback, the tag registry and `.recall.toml`, the MCP server,
and the full CLI.

**Deliberately absent, for v1:** a LanceDB backend, Voyage and Gemini
embedders, a cross-encoder reranker, a file watcher, PDF/DOCX/XLSX
ingestion, and any multi-user or auth story.

## Provenance and licence

MIT, © DBHQ Consulting Ltd — see [LICENSE](LICENSE). Built on published
information-retrieval literature (Reciprocal Rank Fusion: Cormack, Clarke
and Buettcher, 2009; BM25: Robertson and Spärck Jones) and on the public
documentation of pgvector, Postgres, ParadeDB `pg_search`, Ollama and MCP.
Informed by the wider prior art in code- and note-retrieval tooling; its own
implementation is original to this repository.

<div align="center">
<br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo/recall-mark-dark.svg">
  <img alt="" src="assets/logo/recall-mark-light.svg" width="40">
</picture>
</div>
</content>
