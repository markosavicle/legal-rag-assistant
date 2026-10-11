import psycopg
from pgvector.psycopg import register_vector

from app.config import settings

# 'simple' text search config: Postgres ships no Serbian stemmer, so we index raw lowercased tokens.
SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id          SERIAL PRIMARY KEY,
    filename    TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id           SERIAL PRIMARY KEY,
    document_id  INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  INT NOT NULL,
    page         INT,
    content      TEXT NOT NULL,
    embedding    vector({settings.embedding_dim}) NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);

-- Re-ingesting the same text never pays for the same embedding twice.
CREATE TABLE IF NOT EXISTS embedding_cache (
    text_hash  TEXT PRIMARY KEY,
    model      TEXT NOT NULL,
    embedding  vector({settings.embedding_dim}) NOT NULL
);
"""


def init_db() -> None:
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute(SCHEMA)


def connect() -> psycopg.Connection:
    conn = psycopg.connect(settings.database_url, autocommit=True)
    register_vector(conn)
    return conn
