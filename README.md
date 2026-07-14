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
&nbsp;![Status: design in progress](https://img.shields.io/badge/status-design%20in%20progress-8A99B0?style=flat-square)

</div>

---

## What recall is

recall indexes your notes and your code, searches them with **BM25 and dense
vectors fused by Reciprocal Rank Fusion**, and returns ranked passages to your
coding agent over MCP. Two things set it apart from the code-search tools in
this space:

- **It is built for prose first.** Markdown gets heading-aware chunking that
  carries its heading trail into the embedding. Code is supported and chunked
  properly, but notes are not a second-class citizen bolted onto a code tool.
- **It never degrades silently.** If the real BM25 ranker is missing, or the
  lexical half of a query returns nothing, recall says so in the response. A
  hybrid search that has quietly become a dense-only search is worse than
  useless, because it looks like it is working.

## Why it exists

recall is for the queries grep cannot serve: the ones where you do not know the
words you are looking for. Lexical search over code is already excellent in
every agent harness, so recall does not try to replace it. It fuses lexical
precision with semantic recall, and it is honest when one of those halves has
nothing to add.

| Principle | What it means |
| --- | --- |
| **Local by default** | Nothing leaves the machine unless you explicitly configure a cloud embedder. No hosted component, no telemetry. |
| **Honest failure** | Every degradation is reported in-band. No silent fallbacks. |
| **Portable identity** | An index is addressed by tag, never by filesystem path, so it survives moving machines. |
| **Boring on purpose** | Full re-index over incremental cleverness. At realistic sizes a rebuild is seconds, and a rebuild is always correct. |

## How it works

<div align="center">

**lexical (BM25)** &nbsp;+&nbsp; **dense (vectors)** &nbsp;→&nbsp; **Reciprocal Rank Fusion** &nbsp;→&nbsp; **ranked passages**

</div>

A query runs against two rankers at once: a lexical ranker over a full-text
index and a dense ranker over embeddings. Their two result lists are fused with
[Reciprocal Rank Fusion](https://plg.uwaterloo.ca/~gvcormack/cormacksigir09-rrf.pdf)
(Cormack, Clarke & Buettcher, 2009), which needs no score calibration between
the halves. If either half comes back empty, the response says so, and says
whether what you are reading is hybrid or dense-only.

Every chunk is identified by `{tag}:{rel_path}:{chunk_idx}`. A **source** is one
indexed body of material (a repo, a notes folder, a docs tree), named by a short
stable **tag** like `brain` or `dbhq`. Paths resolve to absolute only at read
time, on the machine doing the reading, so no absolute path is ever written to
the store.

## Stack

Postgres with [`pgvector`](https://github.com/pgvector/pgvector) for dense search
and [`pg_search`](https://github.com/paradedb/paradedb) for BM25, embeddings from
a local [Ollama](https://ollama.com) running `nomic-embed-text` (768-dim), and an
[MCP](https://modelcontextprotocol.io) server so any agent can call it.

## Status

> **Design in progress. Nothing is built yet.**
> The approved design is the source of truth: **[`docs/design.md`](docs/design.md)**.

**Out of scope for v1:** LanceDB, Voyage and Gemini embedders, a cross-encoder
reranker, a file watcher, PDF/DOCX/XLSX ingestion, and any multi-user or auth
story.

## Licence

MIT &nbsp;·&nbsp; DBHQ Consulting Ltd. See [LICENSE](LICENSE).

<div align="center">
<br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo/recall-mark-dark.svg">
  <img alt="" src="assets/logo/recall-mark-light.svg" width="40">
</picture>
</div>
