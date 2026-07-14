from __future__ import annotations

import psycopg
from pgvector.psycopg import register_vector

from recall.errors import DimensionMismatchError, StoreNotInitialisedError
from recall.models import LexicalRanker
from recall.store import sql


class PgVectorStore:
    """pgvector backend. One database, one `chunks` table.

    Silos are a `WHERE source = ANY(...)` predicate, which is why cross-source
    search is nearly free rather than a federation problem.
    """

    def __init__(self, dsn: str, *, pg_search_enabled: bool | None = None) -> None:
        self.dsn = dsn
        self._pg_search_enabled = pg_search_enabled  # None = autodetect

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self.dsn)
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
            return bool(cur.fetchone()[0])

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

    def lexical_ranker(self) -> LexicalRanker:
        """Which ranker is ACTUALLY live. Never optimistic.

        BM25 requires both the extension AND the index. If pg_search was installed
        after `recall init`, the extension exists but the index does not — and
        claiming BM25 then would be precisely the silent degradation this product
        exists to prevent.
        """
        with self._connect() as conn:
            if not self._detect_pg_search(conn):
                return "ts_rank_cd"
            with conn.cursor() as cur:
                cur.execute(sql.HAS_BM25_INDEX)
                has_index = bool(cur.fetchone()[0])
        return "bm25" if has_index else "ts_rank_cd"

    def check_model(self, model: str, dim: int) -> None:
        meta = self._meta()
        stored_model = meta.get("embedding_model", "")
        stored_dim = int(meta.get("embedding_dim", "0"))
        if stored_model != model or stored_dim != dim:
            raise DimensionMismatchError(stored_model, stored_dim, model, dim)
