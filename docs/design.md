# recall - design

**Status:** approved design, not yet built
**Date:** 14 July 2026
**Owner:** DBHQ Consulting Ltd

## What recall is

A local-first hybrid retrieval server for coding agents, spoken over MCP. It indexes your notes and your code, searches them with **BM25 and dense vectors fused by Reciprocal Rank Fusion**, and returns ranked passages.

Two things make it different from the code-search tools in this space:

1. **It is built for prose first.** Markdown gets heading-aware chunking that carries its heading trail into the embedding. Code is supported and chunked properly, but notes are not a second-class citizen bolted on to a code tool.
2. **It never degrades silently.** If the real BM25 ranker is missing, or the lexical half of a query returns nothing, recall says so in the response. A hybrid search that has quietly become a dense-only search is worse than useless, because it looks like it is working.

## What recall is not

- Not a replacement for grep. Lexical search over code is already excellent in every agent harness, and the evidence is that semantic retrieval adds little there. recall is for the queries grep cannot serve: the ones where you do not know the words you are looking for.
- Not a cloud service. There is no hosted component and no telemetry.
- Not a general RAG framework. It does retrieval. It does not chunk PDFs, call LLMs, or manage prompts.

## Principles

- **Local by default.** Nothing leaves the machine unless the user explicitly configures a cloud embedder.
- **Honest failure.** Every degradation is reported in-band. No silent fallbacks.
- **Boring on purpose.** Full re-index over incremental cleverness. At realistic sizes a rebuild is seconds, and a rebuild is always correct.
- **Portable identity.** An index is addressed by tag, never by filesystem path, so it survives moving machines.

## Terminology

A **source** is one indexed body of material: a repo, a notes folder, a docs tree. Each source has a **tag**: a short stable name like `brain` or `dbhq`. Sources are siloed from each other by default; a query can span them when it asks to.

## Source identity and the registry

The central constraint: **an index must survive the source moving to a different machine or a different path.** A path is a machine-local accident. A tag is the identity.

Two layers.

**In-source marker.** A `.recall.toml` at the root of the source declares its tag. This file is committed, so it travels with the source through git and is correct on every machine by construction.

```toml
[source]
tag = "brain"
include = ["**/*.md"]
exclude = ["**/node_modules/**", "**/.git/**"]
```

**Machine-local registry.** `~/.config/recall/registry.toml` maps tag to the local path on *this* machine. It is written by `recall register <path>`, which reads the source's `.recall.toml` to learn the tag.

```toml
[sources.brain]
path = "/home/devops/brain"

[sources.dbhq]
path = "/home/devops/dbhq"
```

**The invariant, which is load-bearing and gets a test:** no absolute path is ever written to the store. Every chunk is identified by `{tag}:{rel_path}:{chunk_idx}`. Paths are resolved to absolute only at read time, through the registry, on the machine doing the reading.

## Architecture

```
                 recall index (CLI)              recall serve (MCP)
                        |                                |
                  ┌─────┴─────┐                    ┌─────┴─────┐
                  │  Walker   │                    │ MCP tools │
                  │ (registry)│                    └─────┬─────┘
                  └─────┬─────┘                          │
                  ┌─────┴─────┐                          │
                  │ Chunkers  │  markdown / code         │
                  └─────┬─────┘                          │
                  ┌─────┴─────┐                          │
                  │ Embedder  │  ollama / openai         │
                  └─────┬─────┘                          │
                        └──────────┬─────────────────────┘
                              ┌────┴────┐
                              │  Store  │  pgvector (v1) / lancedb (v2)
                              └─────────┘
```

Each unit has one job and a narrow interface. The Store knows nothing about markdown. The chunkers know nothing about Postgres. The embedder knows nothing about either.

## Storage: the pgvector schema

One database, one `chunks` table. Silos are a `WHERE source = ANY(...)` predicate, which is why cross-source search is nearly free rather than a federation problem.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- embedding_provider, embedding_model, embedding_dim, schema_version

CREATE TABLE chunks (
  id         BIGSERIAL PRIMARY KEY,
  source     TEXT NOT NULL,
  rel_path   TEXT NOT NULL,
  chunk_idx  INT  NOT NULL,
  content    TEXT NOT NULL,
  context    TEXT,               -- heading trail (prose) or symbol name (code)
  lang       TEXT,
  file_sha   TEXT NOT NULL,      -- change detection
  embedding  VECTOR(:dim) NOT NULL,
  tsv        TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
  indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source, rel_path, chunk_idx)
);

CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_idx       ON chunks USING gin (tsv);
CREATE INDEX chunks_source_idx    ON chunks (source);
CREATE INDEX chunks_file_idx      ON chunks (source, rel_path);
```

`:dim` is substituted at `recall init` from the configured embedding model. A vector column has one fixed width, so **the embedding model is fixed for the life of the database**. `meta` records it, and `recall index` hard-errors on a mismatch rather than writing a corrupt index. Changing model means `recall reindex`.

## The lexical half, and the BM25 wart

Postgres full-text search is **not BM25**. `ts_rank_cd` is a cover-density ranker with no term-frequency saturation and no document-length normalisation. It is a real ranker and it is usable; it is simply not the thing the literature means by BM25.

Real BM25 inside Postgres requires the [ParadeDB `pg_search`](https://github.com/paradedb/paradedb) extension.

**Design decision: support both, and always say which one is live.**

- If `pg_search` is present, the lexical CTE scores with BM25.
- If it is absent, we fall back to `ts_rank_cd`.
- `recall doctor` reports which ranker is active and warns on the fallback.
- `recall_status` (MCP) reports it too, so the agent knows what it is holding.

This is deliberately the opposite of the norm in this space, where a missing lexical index degrades the tool to dense-only search and nobody finds out.

## Fusion: RRF

Reciprocal Rank Fusion, per Cormack, Clarke and Buettcher (2009). Each half retrieves a pool of `limit * 3`, and a document's score is the sum of `1 / (k + rank)` across the halves it appears in. Configurable, and generalised to a weighted convex combination (see `store/sql.py`).

**Default `k = 10`, not the paper's 60** — and deliberately not presented as a measured win. On the golden set the two are statistically indistinguishable (see the decision log). It is kept as a prior that suits a top-10 use case, not as a result. See `RecallConfig.rrf_k` for the numbers and the provenance.

In pgvector this is a single SQL statement, which is the main aesthetic argument for the Postgres backend:

```sql
WITH dense AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> :qvec) AS rank
  FROM chunks
  WHERE source = ANY(:sources)
  ORDER BY embedding <=> :qvec
  LIMIT :pool
),
lexical AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(tsv, q) DESC) AS rank
  FROM chunks, websearch_to_tsquery('english', :qtext) q
  WHERE source = ANY(:sources) AND tsv @@ q
  ORDER BY ts_rank_cd(tsv, q) DESC
  LIMIT :pool
)
SELECT c.id, c.source, c.rel_path, c.context, c.content,
       COALESCE(1.0 / (:k + d.rank), 0) + COALESCE(1.0 / (:k + l.rank), 0) AS score
FROM chunks c
LEFT JOIN dense   d ON d.id = c.id
LEFT JOIN lexical l ON l.id = c.id
WHERE d.id IS NOT NULL OR l.id IS NOT NULL
ORDER BY score DESC
LIMIT :limit;
```

RRF's `k = 60` is a convention, not a law. The literature is clear that it is sensitive to tuning and that convex combination can beat it. We let the golden set decide, and it declined to: `k=10` and `k=60` are statistically indistinguishable on our corpus (decision log, 17 July 2026). We ship 10 as a prior suited to top-10 retrieval, not as a measured win — and we say so rather than dressing a null result up as tuning.

## Chunking

This is where retrieval quality is actually won or lost, and where recall differs most from the code-first tools.

**Markdown - heading-aware.** Parse the heading structure and emit a chunk per leaf section. **Prepend the heading trail into the embedded text**, so a chunk that reads "we went with the pop-top" still embeds as `Areas > Travel > Van conversion > Decision` plus that body. Without this, a passage loses the context that makes it findable.

- Sections under ~200 characters merge forward into the next.
- Sections over ~2000 characters split on paragraph boundaries with ~150 characters of overlap.
- The trail is also stored in `context` so results can display it without re-parsing.

**Code - AST-aware.** tree-sitter, chunked at function and class boundaries, with the symbol name in `context`. Unsupported languages fall back to 60-line windows with 10-line overlap.

The evidence on chunking is genuinely mixed and the effect sizes are small. Do not spend a week here. Get it sane and move on to the reranker, which matters more.

## Embeddings

```python
class Embedder(Protocol):
    name: str           # "ollama:nomic-embed-text"
    dim: int
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...
```

Documents and queries get **separate methods on purpose**. Several strong local models are asymmetric and want a task prefix (`search_document:` versus `search_query:`). Collapsing them into one `embed()` is a quiet correctness bug that costs retrieval quality and is invisible at query time.

**Default: `nomic-embed-text` via Ollama.** 768 dimensions, 8192-token context. The obvious alternative, `all-MiniLM-L6-v2`, truncates input at 256 word pieces by default, which silently discards the tail of any chunk longer than a short paragraph. It is not a candidate.

v1 ships **Ollama** and **OpenAI**. Voyage and Gemini come later behind the same interface.

## Backends

```python
class Store(Protocol):
    def init(self, dim: int, model: str) -> None: ...
    def upsert(self, chunks: list[Chunk]) -> None: ...
    def delete_source(self, tag: str) -> None: ...
    def prune(self, tag: str, seen: set[str]) -> int: ...
    def search(self, qvec, qtext, sources, limit, k) -> SearchResult: ...
    def lexical_ranker(self) -> str: ...   # "bm25" | "ts_rank_cd" | "tantivy"
    def stats(self) -> Stats: ...
```

**v1 implements pgvector only.** LanceDB is the second backend and its job is the zero-setup story: an embedded, no-daemon, no-Postgres path for someone trying recall for the first time. It brings its own BM25 (Tantivy), so it satisfies the hybrid contract without a server.

ChromaDB was considered and rejected. It has recently gained BM25 sparse vectors and RRF, so it is a genuine hybrid store, but its own documentation demonstrates hybrid search exclusively through `CloudClient` and does not state whether it works in the embedded `PersistentClient`. For the backend whose entire purpose is "works locally with no server", "embedded by construction" beats "embedded, we think".

## The MCP surface

| Tool | Purpose |
|---|---|
| `recall_search(query, sources=None, limit=10)` | The one that matters. `sources` defaults to the current source. Pass a list to span silos, or `["*"]` for everything. |
| `recall_sources()` | What is indexed: tag, chunk count, last indexed. |
| `recall_status()` | Health: which lexical ranker is live, which embedding model, dimension, backend. |

**Silo semantics.** The server resolves a current source at launch, either from `--source <tag>` or by walking up from the working directory for a `.recall.toml`. Queries default to that source. Crossing a silo is explicit and deliberate, which is the point: an agent working in `dbhq` should not silently pull context out of `brain` unless it asked to.

**Indexing is not an MCP tool.** It is a CLI command (`recall index <tag>`). Indexing is slow and mutating, and an agent should not be able to kick one off in the middle of a conversation. If this turns out to be annoying in practice, revisit it, but start restrictive.

## Freshness

Walk the source, hash each file, skip files whose `file_sha` is unchanged, upsert the rest, delete chunks whose files have disappeared. That is the entire freshness strategy.

No Merkle trees, no content-addressed caches, no file watcher. Those exist to make re-indexing cheap at a scale we are nowhere near. A rebuild at realistic sizes takes seconds, and a rebuild is always correct.

## Failure modes

Each of these is a deliberate, reported failure rather than a silent one.

| Condition | Behaviour |
|---|---|
| `pg_search` absent | Fall back to `ts_rank_cd`. Reported by `doctor` and `recall_status`. |
| Lexical half returns zero hits | Return dense-only results, and say so in the response metadata. Never present it as a hybrid result. |
| Configured model's dim != stored dim | Hard error. Refuse to index. Tell the user to reindex. |
| Ollama unreachable | Hard error naming the exact endpoint and the fix. Never fall back to a different model. |
| Source tag not in registry | Hard error listing the known tags. |

## Testing

- **Golden queries are the only number that matters.** 30 to 50 real queries against a fixture source, each with a known correct answer, scored on Recall@10 and MRR. Public code-retrieval benchmarks are contaminated (their queries are often derived from the target text verbatim) and will flatter us. Build this early; it is the thing that tells us whether any of the rest worked.
- **Unit:** the markdown chunker's heading trail, the code chunker's symbol boundaries, RRF arithmetic against a hand-worked example, and the path-independence invariant (index a source at one path, move it, re-register, confirm queries still resolve).
- **Integration:** real Postgres, real pgvector, both with and without `pg_search` present, to prove the fallback path is honest.

## Measured results: BEIR

*(Added 16 July 2026.)* The golden query set above is ours: we wrote both
the queries and the relevance labels, and — see `docs/eval/README.md` — it
once said fusion loses to dense-only on our own fixture. That is a
synthetic-eval failure mode, not necessarily a fusion failure mode: our
fixture is small and semantic-skewed, and it is the only corpus that has
ever seen these exact queries. So we adopted an external, un-authored
benchmark to settle the question: [BEIR](https://github.com/beir-cellar/beir)
(Thakur et al., 2021), which ships fixed corpora, fixed queries and
published baselines for BM25, DPR, ANCE, TAS-B and ColBERT.

**BEIR SciFact** (5,183 docs, 300 queries), NDCG@10: recall hybrid **0.711**,
recall dense-only 0.700, ColBERT (published) 0.671, BM25 (published) 0.665,
TAS-B (published) 0.643, recall lexical-only 0.639, ANCE (published) 0.507,
DPR (published) 0.318.

**BEIR NFCorpus** (3,633 docs, 323 queries), NDCG@10: recall hybrid
**0.339**, BM25 (published) 0.325, recall dense-only 0.320, TAS-B
(published) 0.319, ColBERT (published) 0.305, recall lexical-only 0.303,
ANCE (published) 0.237, DPR (published) 0.189.

**The vindication: fusion beats both halves on both datasets**
(SciFact 0.711 > 0.700 > 0.639; NFCorpus 0.339 > 0.320 > 0.303), and
recall's hybrid beats the published BM25 baseline on both (+0.046 SciFact,
+0.014 NFCorpus). This confirms the design's central bet — stated at the top
of this document — that fusing BM25 and dense retrieval with RRF outperforms
either half alone. The fixture's contrary result was the fixture's own
artefact, not the truth about recall.

Two caveats keep this honest rather than triumphant. BEIR documents are
short abstracts (roughly 1.1 chunks per document), so this validates
recall's **ranking and fusion**, not its chunking. And our lexical arm sits
−0.026 (SciFact) / −0.022 (NFCorpus) below published BM25, inside the ±0.05
band that Kamalloo et al. (SIGIR 2024) attribute to ordinary
index-configuration differences — i.e. our BM25 reproduces the reference
rather than merely resembling it.

Full methodology, the SWE-bench code-retrieval slice, and the reranker
literature review live in `eval/beir.py`, `eval/swebench.py` and
`docs/research/`.

## Scope

**In, for v1**

- [ ] Python package, `uvx`-installable
- [ ] pgvector backend
- [ ] Ollama and OpenAI embedders
- [ ] Markdown (heading-aware) and code (tree-sitter) chunkers
- [ ] RRF fusion, BM25 via `pg_search` with an honest `ts_rank_cd` fallback
- [ ] Tag registry, `.recall.toml`, cross-machine path independence
- [ ] MCP server: `recall_search`, `recall_sources`, `recall_status`
- [ ] CLI: `init`, `register`, `index`, `reindex`, `sources`, `doctor`, `serve`
- [ ] Golden query harness

**Out, for v1 (interfaces ready, implementations later)**

- LanceDB backend
- Voyage and Gemini embedders
- Cross-encoder reranker
- File watcher
- PDF, DOCX, XLSX ingestion
- Any multi-user or auth story

**Roadmap after v1, in priority order**

1. **Cross-encoder reranker — conditional, not assumed.** *(Corrected 16 July 2026 — see below.)* This item originally read "the largest measured quality win available to us, ahead of any backend or model swap. Do this before anything else on this list." We built it and measured it: off-the-shelf cross-encoder reranking (`ms-marco-MiniLM-L-6-v2` and `bge-reranker-base`, both applied to the fixture golden set) **degraded retrieval**, dropping MRR below the no-rerank hybrid baseline. This is consistent with the 2024–2026 literature, which finds reranking helps a *weak* first-stage retriever (classic BM25-then-rerank); recall's first stage is already a strong 2024 dense model, and an off-the-shelf, domain-mismatched cross-encoder adds noise rather than signal on top of it. The item stays on the roadmap but demoted to **conditional and unproven**: it is not worth attempting again without either a stronger or domain-tuned reranker, and any future attempt must be gated on a measured lift against the golden set before it ships — never on faith. See `docs/research/` for the full literature review.
2. **LanceDB backend.** Unlocks the zero-setup install and proves the Store interface is real.
3. **Voyage and Gemini embedders.**
4. **Go public.** Flip the repo, publish the package, write the launch post.

## Provenance

recall draws on published information-retrieval literature (Reciprocal Rank Fusion: Cormack, Clarke and Buettcher, 2009; BM25: Robertson and Spärck Jones), on the public documentation of pgvector, Postgres, ParadeDB pg_search, LanceDB, Ollama and MCP, and on the wider prior art in code- and note-retrieval tooling. The techniques it uses — rank fusion, dense + lexical hybrid retrieval, heading-aware chunking — are standard and unencumbered. Its own code is original to this repository.

## Decision log

Decisions that changed a default or closed an open question, with the evidence.
This section exists because `rrf_k` once drifted from 60 to 10 inside a commit
about something else, contradicting a recorded decision, and nobody could later
say why. A default without a paper trail is a guess wearing a lab coat.

### `rrf_k` stays 10, and it is not a measured win *(17 July 2026)*

**Question.** `RecallConfig.rrf_k` shipped as 10 while this document and
`docs/eval/README.md` both said 60 — the latter having explicitly concluded
"k=60 stays". Which is right?

**Measurement.** Golden set (40 queries), real Ollama `nomic-embed-text`, real
BM25 via pg_search, `limit=10`. Paired bootstrap over queries, 2000 resamples:

| comparison | delta (k=10 − k=60) | 95% CI | verdict |
|---|---:|---|---|
| Recall@10 | −0.025 | [−0.075, +0.000] | includes 0 — indistinguishable |
| MRR | +0.023 | [−0.019, +0.076] | includes 0 — indistinguishable |

The full sweep is flat: Recall@10 sits at 0.875–0.900 across every k from 1 to
200, and MRR declines gently from 0.720 (k=1) to 0.622 (k≥60). Every movement
is within noise for n=40.

**Decision.** Keep 10; fix the docs, not the code. The evidence favours neither
value, so churning a shipped default would repeat the original error in the
opposite direction. A low k weights the head of each ranking more heavily,
which suits retrieval feeding an agent's top-10 context. This is recorded as a
**prior, not a result** — if the golden set grows enough to separate them,
revisit and bring a number.

**Process note.** The real defect was never the value. It was that a default
changed silently, against a recorded decision, in a commit about fusion
weights. Hence this log.

### Fusion does not currently beat dense-only on the fixture *(17 July 2026)*

Measured in the same run, `w_dense=0.7 / w_lexical=0.3`, k=10:

| arm | Recall@10 | MRR |
|---|---|---|
| dense | 0.900 [0.800–0.975] | 0.735 [0.617–0.849] |
| lexical | 0.725 [0.575–0.850] | 0.510 [0.371–0.646] |
| **hybrid** | 0.875 [0.774–0.975] | 0.645 [0.530–0.761] |

Hybrid loses to dense-only on both metrics on this corpus. On `semantic`
queries the hybrid-vs-dense delta is *not* distinguishable from noise at n=15;
on `lexical` and `hybrid` kinds every arm saturates Recall@10 at 1.000, so
fusion has nothing to add there. This is consistent with the BEIR results
(where hybrid does win on external, un-authored corpora) and with the
literature's "strong first stage" finding — see `docs/research/`. It is
recorded here rather than quietly averaged away. The honest reading: on a
small, semantic-skewed, self-authored fixture, a strong dense retriever is
hard to improve on by fusing a weak lexical half into it.

## Open questions

- **Fusion's value is corpus-dependent and we should say so.** It wins on BEIR, loses on our fixture. The open question is not "is RRF good" but "for which query distributions does the lexical half add signal rather than noise" — per-query adaptive weighting is the literature's answer and is unbuilt here.
- **English-only tsvector.** `to_tsvector('english', ...)` is hardcoded. Fine for now, wrong for a public tool eventually. Untested against non-Latin scripts: we do not currently know whether a non-English query degrades to zero lexical hits (correctly reported as dense-only) or does something stranger.
- **Chunk size targets are guesses.** ~200 char floor and ~2000 char ceiling are plausible, not measured. The golden set should settle them — the harness sweeps `k` but has no equivalent sweep over chunk size, so this question is still open for the same reason it always was: nobody built the measurement.
