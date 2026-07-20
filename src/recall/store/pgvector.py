from __future__ import annotations

import contextlib
from datetime import datetime

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from recall.errors import (
    DimensionMismatchError,
    InvalidLimitError,
    RecallError,
    StoreNotInitialisedError,
)
from recall.models import Chunk, LexicalRanker, SearchHit, SearchResult, Stats
from recall.store import sql


class PgVectorStore:
    """pgvector backend. One database, one `chunks` table.

    Silos are a `WHERE source = ANY(...)` predicate, which is why cross-source
    search is nearly free rather than a federation problem.
    """

    def __init__(self, dsn: str, *, pg_search_enabled: bool | None = None) -> None:
        self.dsn = dsn
        self._pg_search_enabled = pg_search_enabled  # None = autodetect

    @contextlib.contextmanager
    def _conn(self, conn: psycopg.Connection | None = None):
        """Reuse `conn` if the caller already has one open, else open one.

        This is the whole trick behind "one logical search, one connection":
        lexical_ranker(), _resolve_sources() and the search statement itself
        each accept an optional conn and thread it through here, so a caller
        that already holds a connection never causes a second one to open.
        We do NOT close a conn we did not open — that is the caller's.
        """
        if conn is not None:
            yield conn
        else:
            with self._connect() as owned:
                yield owned

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self.dsn)
        # A brand-new database has no `vector` type until `CREATE EXTENSION
        # vector` runs. init() (which creates it) and drop_all() (which runs
        # before init() in the store_factory fixture order, and never touches
        # a vector column) are the only callers that may legitimately connect
        # before that point — every other method here is only ever called
        # once init() has.
        with contextlib.suppress(psycopg.ProgrammingError):
            register_vector(conn)
        return conn

    def _detect_pg_search(self, conn: psycopg.Connection) -> bool:
        if self._pg_search_enabled is not None:
            return self._pg_search_enabled
        with conn.cursor() as cur:
            try:
                cur.execute(sql.CREATE_PG_SEARCH_EXTENSION)
                conn.commit()
            except psycopg.Error:
                conn.rollback()
                return False
            cur.execute(sql.HAS_PG_SEARCH)
            row = cur.fetchone()
            assert row is not None  # SELECT EXISTS(...) always returns exactly one row
            return bool(row[0])

    def init(self, dim: int, model: str, provider: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.CREATE_VECTOR_EXTENSION)
            conn.commit()

            enabled = self._detect_pg_search(conn)
            self._pg_search_enabled = enabled

            with conn.cursor() as cur:
                cur.execute(sql.CREATE_META)
                cur.execute(sql.CREATE_CHUNKS.format(dim=dim))
                for stmt in sql.CREATE_INDEXES:
                    cur.execute(stmt)
                if enabled:
                    cur.execute(sql.CREATE_BM25_INDEX)

                for key, value in {
                    "embedding_provider": provider,
                    "embedding_model": model,
                    "embedding_dim": str(dim),
                    "schema_version": sql.SCHEMA_VERSION,
                }.items():
                    cur.execute(
                        "INSERT INTO meta (key, value) VALUES (%s, %s) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                        (key, value),
                    )
            conn.commit()

    def drop_all(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql.DROP_ALL)
            conn.commit()

    def _meta(self) -> dict[str, str]:
        with self._connect() as conn, conn.cursor() as cur:
            try:
                cur.execute("SELECT key, value FROM meta")
            except psycopg.errors.UndefinedTable as exc:
                raise StoreNotInitialisedError(
                    "This database has no recall schema. Run:  recall init"
                ) from exc
            return dict(cur.fetchall())

    def lexical_ranker(self, conn: psycopg.Connection | None = None) -> LexicalRanker:
        """Which ranker is ACTUALLY live. Never optimistic, never cached.

        BM25 requires both the extension AND the index. If pg_search was installed
        after `recall init`, the extension exists but the index does not — and
        claiming BM25 then would be precisely the silent degradation this product
        exists to prevent. This is checked live on every call — do NOT memoize
        the result across calls the way _detect_pg_search memoizes the extension
        check; a stale cached "bm25" would be exactly the lie this product exists
        to catch. Pass `conn` to reuse an already-open connection.
        """
        with self._conn(conn) as c:
            if not self._detect_pg_search(c):
                return "ts_rank_cd"
            with c.cursor() as cur:
                cur.execute(sql.HAS_BM25_INDEX)
                row = cur.fetchone()
                assert row is not None  # SELECT EXISTS(...) always returns exactly one row
                has_index = bool(row[0])
        return "bm25" if has_index else "ts_rank_cd"

    def check_model(self, model: str, dim: int) -> None:
        meta = self._meta()
        stored_model = meta.get("embedding_model", "")
        stored_dim = int(meta.get("embedding_dim", "0"))
        if stored_model != model or stored_dim != dim:
            raise DimensionMismatchError(stored_model, stored_dim, model, dim)

    def upsert(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        rows = []
        for c in chunks:
            if c.embedding is None:
                # Honest failure: a chunk with no vector is a bug upstream (the
                # indexer embeds before upserting). Say so plainly rather than
                # handing None to pgvector and getting an opaque driver error.
                raise RecallError(
                    f"Chunk {c.chunk_id!r} has no embedding. Chunks must be embedded "
                    f"before they reach the store. Refusing to write a chunk with no vector."
                )
            rows.append(
                (
                    c.source,
                    c.rel_path,
                    c.chunk_idx,
                    c.content,
                    c.context,
                    c.lang,
                    c.file_sha,
                    Vector(c.embedding),
                )
            )
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO chunks
                    (source, rel_path, chunk_idx, content, context, lang, file_sha, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source, rel_path, chunk_idx) DO UPDATE SET
                    content    = EXCLUDED.content,
                    context    = EXCLUDED.context,
                    lang       = EXCLUDED.lang,
                    file_sha   = EXCLUDED.file_sha,
                    embedding  = EXCLUDED.embedding,
                    indexed_at = now()
                """,
                rows,
            )
            conn.commit()

    def delete_source(self, tag: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE source = %s", (tag,))
            conn.commit()

    def delete_file(self, tag: str, rel_path: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE source = %s AND rel_path = %s", (tag, rel_path))
            conn.commit()

    def prune(self, tag: str, seen: set[str]) -> int:
        """Delete chunks whose files have disappeared from the source.

        This, plus the file_sha skip, IS the freshness strategy. No Merkle trees,
        no content-addressed caches, no file watcher.
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM chunks WHERE source = %s AND NOT (rel_path = ANY(%s))",
                (tag, list(seen)),
            )
            removed = cur.rowcount
            conn.commit()
        return removed

    def file_shas(self, tag: str) -> dict[str, str]:
        """rel_path -> file_sha for everything currently indexed under this tag."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT rel_path, file_sha FROM chunks WHERE source = %s", (tag,))
            return dict(cur.fetchall())

    def stats(self) -> Stats:
        meta = self._meta()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql.STATS_BY_SOURCE)
            rows = cur.fetchall()
        by_source: dict[str, int] = {source: count for source, count, _last_indexed in rows}
        last_indexed: dict[str, datetime | None] = {
            source: last_indexed for source, _count, last_indexed in rows
        }
        return Stats(
            sources=by_source,
            total_chunks=sum(by_source.values()),
            embedding_provider=meta.get("embedding_provider", "unknown"),
            embedding_model=meta.get("embedding_model", "unknown"),
            embedding_dim=int(meta.get("embedding_dim", "0")),
            lexical_ranker=self.lexical_ranker(),
            last_indexed=last_indexed,
        )

    POOL_MULTIPLIER = 3

    # Upper bound on `limit`. With POOL_MULTIPLIER=3 this caps each half's
    # candidate CTE at 600 rows for a single query — plenty of headroom for
    # RRF to have real candidates to fuse, without letting one query fan out
    # into an unbounded scan. A caller wanting more than 200 ranked results
    # should page across calls, not widen a single one. We error rather than
    # silently clamp: a clamp would be a quiet lie about what was searched.
    MAX_LIMIT = 200

    def _validate_limit(self, limit: int) -> None:
        if limit < 1 or limit > self.MAX_LIMIT:
            raise InvalidLimitError(limit, self.MAX_LIMIT)

    def _resolve_sources(
        self, sources: list[str], conn: psycopg.Connection | None = None
    ) -> list[str]:
        """`["*"]` means every silo. Resolve it rather than branching the SQL."""
        if "*" not in sources:
            return sources
        with self._conn(conn) as c, c.cursor() as cur:
            cur.execute(sql.ALL_SOURCES)
            return [r[0] for r in cur.fetchall()]

    def search(
        self,
        qvec: list[float],
        qtext: str,
        sources: list[str],
        limit: int = 10,
        k: int = 60,
        w_dense: float = 1.0,
        w_lexical: float = 1.0,
    ) -> SearchResult:
        """Hybrid retrieval: dense + lexical, fused by a weighted convex combination
        of RRF terms, in one SQL statement.

        The defaults (w_dense=1.0, w_lexical=1.0) reproduce textbook,
        unweighted RRF exactly (Cormack, Clarke and Buettcher, 2009) — the store
        is a mechanism, not a policy. The dense-leaning default weighting
        (w_dense=0.7, w_lexical=0.3) lives in RecallConfig and is passed in by
        callers that have loaded config.

        The returned SearchResult reports which lexical ranker was actually live
        and whether the lexical half contributed anything at all. It is never
        allowed to look like a healthy hybrid result when it is not one.

        One logical search, one connection: lexical_ranker() and
        _resolve_sources() thread the same conn as the search statement below,
        rather than each opening (and closing) their own.
        """
        self._validate_limit(limit)
        with self._connect() as conn:
            ranker = self.lexical_ranker(conn)
            statement = sql.SEARCH_BM25 if ranker == "bm25" else sql.SEARCH_TS_RANK_CD
            resolved = self._resolve_sources(sources, conn)

            if not resolved:
                return SearchResult(
                    hits=[], lexical_ranker=ranker, dense_hit_count=0, lexical_hit_count=0
                )

            params = {
                "qvec": Vector(qvec),
                "qtext": qtext,
                "sources": resolved,
                "pool": limit * self.POOL_MULTIPLIER,
                "k": k,
                "limit": limit,
                "w_dense": w_dense,
                "w_lexical": w_lexical,
            }

            with conn.cursor() as cur:
                cur.execute(statement, params)
                rows = cur.fetchall()

        hits = [
            SearchHit(
                chunk_id=f"{source}:{rel_path}:{chunk_idx}",
                source=source,
                rel_path=rel_path,
                chunk_idx=chunk_idx,
                context=context,
                content=content,
                lang=lang,
                score=float(score),
                dense_rank=dense_rank,
                lexical_rank=lexical_rank,
            )
            for (
                _id,
                source,
                rel_path,
                chunk_idx,
                context,
                content,
                lang,
                score,
                dense_rank,
                lexical_rank,
            ) in rows
        ]

        return SearchResult(
            hits=hits,
            lexical_ranker=ranker,
            dense_hit_count=sum(1 for h in hits if h.dense_rank is not None),
            lexical_hit_count=sum(1 for h in hits if h.lexical_rank is not None),
        )

    # -------------------------------------------------------------------
    # Eval-support only. Not part of the Store protocol: `search()` above is
    # what production ever calls. These serve one half at a time, unfused, so
    # eval/harness.py can score each arm against its own true top-`limit`
    # ranking rather than deriving a baseline by re-sorting the fused pool
    # (biased — the fused result only contains docs that survived fusion).
    # -------------------------------------------------------------------

    def search_dense_only(
        self, qvec: list[float], sources: list[str], limit: int = 10
    ) -> list[str]:
        """The dense half's true top-`limit`, by cosine distance. rel_path per rank."""
        self._validate_limit(limit)
        with self._connect() as conn:
            resolved = self._resolve_sources(sources, conn)
            if not resolved:
                return []
            with conn.cursor() as cur:
                cur.execute(
                    sql.SEARCH_DENSE_ONLY,
                    {"qvec": Vector(qvec), "sources": resolved, "limit": limit},
                )
                return [row[0] for row in cur.fetchall()]

    def search_lexical_only(self, qtext: str, sources: list[str], limit: int = 10) -> list[str]:
        """The lexical half's true top-`limit`. rel_path per rank.

        Uses whichever ranker is ACTUALLY live, per lexical_ranker(): real BM25
        via paradedb.match when the bm25 index exists, ts_rank_cd otherwise.
        Never bare `@@@` with user text — see CLAUDE.md, it raises on a colon.
        """
        self._validate_limit(limit)
        with self._connect() as conn:
            resolved = self._resolve_sources(sources, conn)
            if not resolved:
                return []
            ranker = self.lexical_ranker(conn)
            statement = (
                sql.SEARCH_LEXICAL_ONLY_BM25
                if ranker == "bm25"
                else sql.SEARCH_LEXICAL_ONLY_TS_RANK_CD
            )
            with conn.cursor() as cur:
                cur.execute(statement, {"qtext": qtext, "sources": resolved, "limit": limit})
                return [row[0] for row in cur.fetchall()]
