---
status: accepted
date: 2025-04-08
deciders: S. Lindqvist, R. Okafor
---

# ADR 006: Embedding provider for incident report similarity

## Status

Accepted. Supersedes nothing; complements ADR 004, which settled *where* the
vectors are stored and explicitly did not settle *who computes them*.

## Context

ADR 004 chose pgvector as the store and, in doing so, closed out the question of
whether we needed a separate vector database at all — ChromaDB, Pinecone and
Weaviate were all considered there and all rejected there, and this ADR does not
reopen any of that. What ADR 004 deliberately left open was the embedding model
itself. The pipeline described there calls OpenAI's `text-embedding-3-small` and
writes a 1536-dimension vector, and that choice was made informally, under
deadline, by whoever was writing the worker at the time. This ADR is the belated
paperwork, and a check that the informal choice still stands.

The pipeline embeds roughly 6,000 incident reports a day, plus a one-off backfill
of the 2.4 million historical rows. Reports are short — a median of 41 words,
because they are typed by a driver on a phone in a depot car park — and the
retrieval task is "find me five old reports that describe roughly this problem".

## Decision

Stay with OpenAI `text-embedding-3-small` at 1536 dimensions for now, but write
down the exit criteria so the decision is reviewable rather than merely inherited.

## Considered options

### OpenAI `text-embedding-3-small` (chosen)

Costs us around £14 a month at current volume, needs no GPU, no model hosting and
no capacity planning. The 1536-dimension output is comfortably inside pgvector's
HNSW envelope. The obvious objection — that we are shipping driver-written
incident text to a third party — was assessed with the security working group and
accepted on the basis that incident reports contain no patient-equivalent special
category data and no driver location traces; the DPIA records that assessment.

### Self-hosted `bge-base-en` on the existing ECS cluster (rejected, for now)

Technically appealing and would keep all report text inside our own VPC. Rejected
for the same underlying reason ADR 003 rejected Keycloak and ADR 004 rejected a
self-hosted vector database: it is one more stateful thing to run, monitor and be
paged about, and a six-engineer team pays for every one of those in on-call
attention rather than in money. The £14 a month is not what makes this decision.

### OpenAI `text-embedding-3-large` (rejected)

3072 dimensions, roughly 6.5x the cost, and in a bake-off against 200 manually
labelled report pairs it moved recall@5 from 0.81 to 0.83. Not nothing, but not
enough to double the index build time and the on-disk footprint of a 2.4-million
row table.

## Exit criteria

We revisit this ADR if any of the following becomes true:

- We start embedding consignment notes, which *do* carry commercially sensitive
  customer detail and would change the third-party assessment above.
- Report volume passes roughly 50,000 a day, where the per-call cost starts to be
  a line item somebody notices rather than a rounding error.
- A dimension change is forced on us, in which case note that the `vector(1536)`
  column type in ADR 004 is not free to alter — it needs the expand-contract
  treatment described in the migration policy, not an `ALTER TYPE`.

## Consequences

The embedding worker keeps a hard dependency on an external API on the write
path, which is why it consumes `incident_report.created` events asynchronously
rather than embedding inline during report creation: an OpenAI outage delays
similarity search by however long the backlog takes to drain, and does not stop a
driver filing a report.
