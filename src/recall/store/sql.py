"""SQL for the pgvector backend.

The two fusion queries live next to each other on purpose. They are the heart of
the product and the only difference between them is the lexical CTE, so they must
be easy to compare by eye.

Fusion is a weighted convex combination, generalising RRF (Cormack, Clarke and
Buettcher, 2009): a document's score is
w_dense * 1/(k + dense_rank) + w_lexical * 1/(k + lexical_rank), summed across
the halves it appears in. Equal weights (w_dense == w_lexical) reproduce the
RANKING that plain RRF would produce — the two terms are scaled identically, so
relative order is unchanged — and w_dense == w_lexical == 1.0 reproduces the
paper's score exactly. The golden set measured equal weighting losing to
dense-only retrieval on this corpus; RecallConfig's default is a moderate
dense-leaning convex combination (w_dense=0.7, w_lexical=0.3) instead, per the
IR literature (Elastic's weighted-RRF write-up; alpha typically 0.3-0.7). See
eval/harness.py and docs/design.md for the measured comparison.
"""

SCHEMA_VERSION = "1"

CREATE_VECTOR_EXTENSION = "CREATE EXTENSION IF NOT EXISTS vector"
CREATE_PG_SEARCH_EXTENSION = "CREATE EXTENSION IF NOT EXISTS pg_search"

CREATE_META = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
)
"""

# {dim} is substituted at `recall init` from the configured embedding model.
# A vector column has one fixed width, so the model is fixed for the life of the DB.
CREATE_CHUNKS = """
CREATE TABLE IF NOT EXISTS chunks (
  id         BIGSERIAL PRIMARY KEY,
  source     TEXT NOT NULL,
  rel_path   TEXT NOT NULL,
  chunk_idx  INT  NOT NULL,
  content    TEXT NOT NULL,
  context    TEXT,
  lang       TEXT,
  file_sha   TEXT NOT NULL,
  embedding  VECTOR({dim}) NOT NULL,
  tsv        TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
  indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source, rel_path, chunk_idx)
)
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS chunks_embedding_idx "
    "ON chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS chunks_tsv_idx    ON chunks USING gin (tsv)",
    "CREATE INDEX IF NOT EXISTS chunks_source_idx ON chunks (source)",
    "CREATE INDEX IF NOT EXISTS chunks_file_idx   ON chunks (source, rel_path)",
]

# Only created when pg_search is present. The tsv/GIN index above always exists,
# because it IS the fallback.
CREATE_BM25_INDEX = """
CREATE INDEX IF NOT EXISTS chunks_bm25_idx
ON chunks USING bm25 (id, source, content)
WITH (key_field='id')
"""

DROP_ALL = "DROP TABLE IF EXISTS chunks CASCADE; DROP TABLE IF EXISTS meta CASCADE"

HAS_PG_SEARCH = "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'pg_search')"
HAS_BM25_INDEX = "SELECT EXISTS(SELECT 1 FROM pg_indexes WHERE indexname = 'chunks_bm25_idx')"

# ---------------------------------------------------------------------------
# Fusion. The dense CTE and the final SELECT are IDENTICAL in both variants.
# Only the lexical CTE differs.
# ---------------------------------------------------------------------------

_DENSE_CTE = """
dense AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> %(qvec)s) AS rank
  FROM chunks
  WHERE source = ANY(%(sources)s)
  ORDER BY embedding <=> %(qvec)s
  LIMIT %(pool)s
)
"""

# Real BM25, via ParadeDB pg_search.
#
# NOTE — this cost us a bug during planning. The bare `content @@@ 'text'` form
# parses its right-hand side as pg_search's query DSL, so an ordinary user query
# containing a colon ("how do I use foo: bar") raises
#   ERROR: could not parse query string
# `paradedb.match` takes the input as TERMS instead. Verified against pg_search
# 0.24.2: it tolerates colons, unbalanced quotes and parens, and returns zero rows
# rather than erroring when nothing matches. NEVER pass user text to bare @@@.
_LEXICAL_CTE_BM25 = """
lexical AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY paradedb.score(id) DESC) AS rank
  FROM chunks
  WHERE source = ANY(%(sources)s)
    AND id @@@ paradedb.match('content', %(qtext)s)
  ORDER BY paradedb.score(id) DESC
  LIMIT %(pool)s
)
"""

# The honest fallback. ts_rank_cd is a cover-density ranker: no term-frequency
# saturation, no document-length normalisation. It is a real ranker and it is
# usable. It is simply NOT what the literature means by BM25, and we say so.
#
# websearch_to_tsquery is punctuation-safe (verified), so no special handling here.
_LEXICAL_CTE_TS_RANK_CD = """
lexical AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(tsv, q) DESC) AS rank
  FROM chunks, websearch_to_tsquery('english', %(qtext)s) q
  WHERE source = ANY(%(sources)s) AND tsv @@ q
  ORDER BY ts_rank_cd(tsv, q) DESC
  LIMIT %(pool)s
)
"""

_FUSE_TAIL = """
SELECT c.id, c.source, c.rel_path, c.chunk_idx, c.context, c.content, c.lang,
       %(w_dense)s * COALESCE(1.0 / (%(k)s + d.rank), 0)
     + %(w_lexical)s * COALESCE(1.0 / (%(k)s + l.rank), 0) AS score,
       d.rank AS dense_rank,
       l.rank AS lexical_rank
FROM chunks c
LEFT JOIN dense   d ON d.id = c.id
LEFT JOIN lexical l ON l.id = c.id
WHERE d.id IS NOT NULL OR l.id IS NOT NULL
ORDER BY score DESC
LIMIT %(limit)s
"""

SEARCH_BM25 = f"WITH {_DENSE_CTE}, {_LEXICAL_CTE_BM25} {_FUSE_TAIL}"
SEARCH_TS_RANK_CD = f"WITH {_DENSE_CTE}, {_LEXICAL_CTE_TS_RANK_CD} {_FUSE_TAIL}"

# ---------------------------------------------------------------------------
# Eval-support only. These serve one half at a time, unfused, so eval/harness.py
# can score each arm against its own true top-`limit` — never derived by
# re-sorting the fused pool, which would be biased (the fused result only
# contains docs that survived fusion). Not part of the Store protocol used at
# request time; PgVectorStore exposes them as extra methods for the harness.
# ---------------------------------------------------------------------------

SEARCH_DENSE_ONLY = """
SELECT rel_path
FROM chunks
WHERE source = ANY(%(sources)s)
ORDER BY embedding <=> %(qvec)s
LIMIT %(limit)s
"""

# Same paradedb.match rule as the fusion query above: never bare `@@@` with
# user text, it parses the RHS as pg_search's query DSL and raises on a colon.
SEARCH_LEXICAL_ONLY_BM25 = """
SELECT rel_path
FROM chunks
WHERE source = ANY(%(sources)s)
  AND id @@@ paradedb.match('content', %(qtext)s)
ORDER BY paradedb.score(id) DESC
LIMIT %(limit)s
"""

SEARCH_LEXICAL_ONLY_TS_RANK_CD = """
SELECT c.rel_path
FROM chunks c, websearch_to_tsquery('english', %(qtext)s) q
WHERE c.source = ANY(%(sources)s) AND c.tsv @@ q
ORDER BY ts_rank_cd(c.tsv, q) DESC
LIMIT %(limit)s
"""

ALL_SOURCES = "SELECT DISTINCT source FROM chunks ORDER BY source"
STATS_BY_SOURCE = "SELECT source, count(*) FROM chunks GROUP BY source ORDER BY source"
