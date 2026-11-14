"""PostgreSQL + pgvector store; cosine search uses exact scans without an ANN index."""
import json
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .models import Chunk


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is required")
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.database_url = database_url
        self.dimensions = dimensions
        # Keep the existing 2048-d OpenRouter table; other embedding dimensions
        # get their own persistent table so migrations never coerce old vectors.
        self.table_name = "document_chunks" if dimensions == 2048 else f"document_chunks_d{dimensions}"

    def create_schema(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    strategy TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    page INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    embedding vector({self.dimensions}) NOT NULL,
                    PRIMARY KEY (strategy, chunk_id)
                )
            """)
            conn.execute(f"CREATE INDEX IF NOT EXISTS {self.table_name}_strategy_idx ON {self.table_name}(strategy)")

    def describe(self) -> dict[str, Any]:
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute("""
                SELECT current_database(), current_setting('server_version'),
                       (SELECT extversion FROM pg_extension WHERE extname = 'vector')
            """).fetchone()
        return {
            "backend": "PostgreSQL + pgvector",
            "database": row[0],
            "postgresql_version": row[1],
            "pgvector_version": row[2],
            "table": f"public.{self.table_name}",
        }

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ValueError(f"Expected {self.dimensions} dimensions, got {len(vector)}")
        # Replace a strategy atomically so changed/removed source chunks cannot linger.
        with psycopg.connect(self.database_url) as conn:
            conn.execute(f"DELETE FROM {self.table_name} WHERE strategy = %s", (strategy,))
            for chunk, vector in zip(chunks, vectors):
                conn.execute(
                    f"""INSERT INTO {self.table_name}
                       (strategy, chunk_id, document_id, source, page, text, metadata, embedding)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)""",
                    (strategy, chunk.chunk_id, chunk.document_id, chunk.source, chunk.page,
                     chunk.text, Jsonb(chunk.metadata), _vector_literal(vector)),
                )
            stored = conn.execute(
                f"SELECT count(*) FROM {self.table_name} WHERE strategy = %s", (strategy,)
            ).fetchone()[0]
            if stored != len(chunks):
                raise RuntimeError(f"Store verification failed for {strategy}: expected {len(chunks)} rows, found {stored}")
        return stored

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if len(query_vector) != self.dimensions:
            raise ValueError(f"Expected {self.dimensions} query dimensions")
        if top_k <= 0:
            return []
        clauses = ["strategy = %s"]
        where_params: list[Any] = [strategy]
        for key, value in (filters or {}).items():
            clauses.append("metadata->>%s = %s")
            where_params.extend((key, str(value)))
        query = f"""SELECT chunk_id, document_id, source, page, text, metadata,
                          1 - (embedding <=> %s::vector) AS score
                   FROM {self.table_name} WHERE {' AND '.join(clauses)}
                   ORDER BY embedding <=> %s::vector LIMIT %s"""
        # SELECT's distance placeholder appears before the WHERE placeholders.
        params = [_vector_literal(query_vector), *where_params, _vector_literal(query_vector), top_k]
        with psycopg.connect(self.database_url) as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {"chunk_id": r[0], "document_id": r[1], "source": r[2], "page": r[3],
             "text": r[4], "metadata": r[5], "score": float(r[6])}
            for r in rows
        ]


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in vector) + "]"
