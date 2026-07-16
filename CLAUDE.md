# recall

Local-first hybrid retrieval server for coding agents, spoken over MCP. Indexes
notes and code, searches them with BM25 + dense vectors fused by Reciprocal Rank
Fusion, returns ranked passages.

DBHQ Consulting Ltd. MIT. `github.com/dbhq-uk/recall`.

## Docs conventions

- **Plans live directly in `docs/`.** No `docs/superpowers/`, no `docs/plans/`
  subfolder. Name them `docs/YYYY-MM-DD-<feature>.md`.
- `docs/design.md` is the approved design and the source of truth for v1.
- SDD scratch (progress ledger, task briefs, review packages) lives in
  `.superpowers/` and is gitignored. It is not documentation.

## Hard constraints

**Prior art is fair game; our code stays our own.** Study whatever helps —
other retrieval tools (including `claude-context` and its forks), vendor docs,
papers. Borrow ideas and approaches freely. What we do not do is paste in
another project's source verbatim: recall's own implementation is written here,
so the repo stays cleanly licensable under MIT. For mechanism, still prefer the
primary source — pgvector docs, Postgres FTS docs, ParadeDB pg_search docs, the
MCP Python SDK, the Ollama API docs, the RRF paper (Cormack, Clarke & Buettcher,
2009) — because it is more reliable than reading it out of someone's codebase.

**No absolute paths in the store.** Every chunk is identified by
`{tag}:{rel_path}:{chunk_idx}`. A path is a machine-local accident; a tag is the
identity. Paths resolve to absolute only at read time, via the registry, on the
machine doing the reading. This has a dedicated test — keep it passing.

**Honest failure.** Every degradation is reported in-band. No silent fallbacks.
If the lexical half is `ts_rank_cd` rather than real BM25, say so. If the lexical
half returned zero hits, say the results are dense-only and not hybrid. A hybrid
search that has quietly become a dense-only search is worse than useless, because
it looks like it is working.

**v1 scope only.** The design's "Out, for v1" list stays out: LanceDB, Voyage and
Gemini embedders, cross-encoder reranker, file watcher, PDF/DOCX/XLSX ingestion,
any multi-user or auth story.

## Gotchas that cost us

- **Never pass user text to pg_search's bare `@@@`.** It parses its right-hand
  side as a query DSL, so an ordinary query containing a colon
  (`how do I use foo: bar`) raises `ERROR: could not parse query string`. Use
  `id @@@ paradedb.match('content', %(qtext)s)`, which takes the input as terms.
- **`pg_search` requires `shared_preload_libraries = 'pg_search'`** and a genuine
  Postgres restart. Without it, creating a bm25 index hangs or crashes the
  connection.
- **Documents and queries get separate embed methods on purpose.**
  `nomic-embed-text` is asymmetric and wants `search_document:` / `search_query:`
  prefixes. Collapsing them into one `embed()` is a quiet correctness bug: it
  costs retrieval quality and is invisible at query time.
- **Ollama batch embedding is `POST /api/embed`** with `{"input": [...]}`. The
  older `/api/embeddings` (singular, `"prompt"`) is one-at-a-time.

## Environment

Postgres 16 with `vector` 0.6.0 and `pg_search` 0.24.2 (both live). Ollama with
`nomic-embed-text` (768-dim), CPU-only. Databases `recall` and `recall_test`,
role `recall`. DSNs in `~/.recall_dsn`, outside the repo.

## Testing

- **Golden queries are the only number that matters.** `eval/` holds the fixture
  corpus, the 40-query golden set and the harness. It reports dense-only,
  lexical-only and hybrid side by side — if fusion does not beat both halves, say
  so rather than shipping a fusion that fuses nothing.
- Run fast tests: `uv run pytest -m "not integration and not ollama"`
- Run everything: `uv run pytest`
