---
status: accepted
date: 2025-03-11
deciders: R. Okafor, S. Lindqvist
---

# ADR 004: Vector store for incident report similarity search

## Status

Accepted.

## Context

Support agents investigating a delivery exception currently search `incident_reports` - free-text notes logged by drivers and depot staff, roughly 2.4 million rows and growing by around 6,000 a day - using `ILIKE` matching, which misses reports describing the same problem in different words: "pallet shrink-wrap split in transit" versus "load arrived with torn wrapping" never match today. We want to embed each report and retrieve nearest neighbours so an agent immediately sees similar historical cases and how they were resolved.

The embedding pipeline, a worker consuming `incident_report.created` events, calls OpenAI's `text-embedding-3-small` model and produces a 1536-dimension vector per report. We need somewhere to store and query those vectors from core-api, which runs eight Gunicorn workers behind an internal ALB.

## Decision

Store embeddings in the existing `wayfreight-core-prod` Postgres instance using pgvector, in a `vector(1536)` column on `incident_reports`, indexed with HNSW and queried using `<=>` cosine distance. We explicitly reject standing up a dedicated vector database for this feature.

## Considered options

### pgvector (chosen)

The embedding lives in the same row, instance and transaction as the report it describes. One SQL statement can filter by depot, exclude reports already linked to a resolved root-cause ticket, and order by similarity in a single round trip - roughly `SELECT ... WHERE depot_id = $1 ORDER BY embedding <=> $2 LIMIT 5`. Backups, point-in-time recovery and the query dashboards described in `postgres-extensions.md` cover the vector column for free, since it is just another column.

### ChromaDB (rejected)

This is the option we looked at hardest, because it's the fastest thing to bolt onto a Python worker and shows up in almost every "add semantic search in an afternoon" tutorial. We rejected it for four reasons, in order:

1. **Embedded/local persistence mode doesn't suit a multi-process API.** ChromaDB's local mode persists to a DuckDB-and-Parquet store on disk, effectively a single-writer model. Running it inside eight Gunicorn workers would mean funnelling every write through one designated process, or running Chroma as its own server anyway - which erases most of the "just embed it" appeal that made it attractive.
2. **A second persistence system means a second backup story.** RDS automated snapshots, point-in-time recovery and the Tuesday maintenance window already cover all of Wayfreight's data. A standalone Chroma server would need its own snapshot schedule, restore drill and runbook entry - pure overhead relative to pgvector.
3. **No transactional join with relational data.** We regularly need queries such as "the five most similar reports, but only from the same depot, and not already linked to an open root-cause ticket." That's one SQL statement with pgvector; with Chroma it's a vector search followed by a second round trip to Postgres, with the two sources able to disagree.
4. **Scale is comfortably inside pgvector's envelope.** At 2.4 million vectors, an HNSW index on pgvector answers a top-5 query in single-digit milliseconds under our load testing - nowhere near where a purpose-built vector database's extra throughput would justify the operational cost above.

### Pinecone (rejected)

A managed service removes the operational concerns raised against Chroma, but adds an external network hop on the agent's hot path and a per-namespace pricing model hard to justify for one 2.4-million-row table when pgvector is effectively free at our scale.

### Weaviate (rejected)

Self-hosting Weaviate carries the same "second stateful service" problem as self-hosted Chroma, without a compensating advantage for a pattern dominated by filtered nearest-neighbour lookups against data we already keep in Postgres.

## Consequences

- Embedding and report writes share one transaction, simplifying consistency at the cost of a slightly slower report-creation write.
- We inherit pgvector's HNSW build-time memory cost, managed by scheduling `REINDEX` during the Tuesday maintenance window rather than rebuilding online.
- If similarity search expands to consignment-note search across all haulier tenants, we will revisit this - pgvector's advantage narrows well beyond single-digit millions of rows.

## Example query

```python
# similarity_search.py - called from the incident report detail view
def find_similar_reports(report_id: str, depot_id: str, limit: int = 5):
    # embedding is fetched once and reused in the ORDER BY below
    embedding = fetch_embedding(report_id)
    return db.execute(
        "SELECT id, summary, resolution FROM incident_reports "
        "WHERE depot_id = %s AND id != %s "
        "ORDER BY embedding <=> %s LIMIT %s",
        [depot_id, report_id, embedding, limit],
    )
```
