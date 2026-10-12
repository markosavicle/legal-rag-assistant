import psycopg
from pgvector.psycopg import register_vector

from app.config import settings
from app.stemmer import stem_text

# pgvector's HNSW index supports at most 2000 dimensions; above that we fall back to exact search,
# which is fast enough for thousands of chunks.
HNSW_MAX_DIM = 2000

# Postgres ships no Serbian stemmer, so words are stemmed in Python (app/stemmer.py) and stored in
# `stems`; the full-text index uses the 'simple' config on those stems.
SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id          SERIAL PRIMARY KEY,
    filename    TEXT NOT NULL,
    file_hash   TEXT NOT NULL UNIQUE,       -- SHA-256 of the file, so the same file isn't indexed twice
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id           SERIAL PRIMARY KEY,
    document_id  INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  INT NOT NULL,
    page         INT,
    content      TEXT NOT NULL,              -- original text, shown to users and the LLM
    search_text  TEXT NOT NULL,              -- Latin-script copy used for embeddings and article lookup
    stems        TEXT NOT NULL,              -- stemmed search_text, for keyword search
    embedding    vector({settings.embedding_dim}) NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('simple', stems)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks (document_id);

-- Re-ingesting the same text never pays for the same embedding twice.
CREATE TABLE IF NOT EXISTS embedding_cache (
    text_hash  TEXT PRIMARY KEY,
    model      TEXT NOT NULL,
    embedding  vector({settings.embedding_dim}) NOT NULL
);
"""

HNSW_INDEX = "CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops)"


def _existing_dim(conn) -> int | None:
    row = conn.execute(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = to_regclass('chunks') AND attname = 'embedding'"
    ).fetchone()
    return int(row[0].removeprefix("vector(").rstrip(")")) if row else None


# Columns added after the first version; an older database must be reset to get them.
REQUIRED_COLUMNS = [("documents", "file_hash"), ("chunks", "search_text")]


def _missing_columns(conn) -> list[str]:
    missing = []
    for table, column in REQUIRED_COLUMNS:
        exists_table = conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]
        if exists_table and not _has_column(conn, table, column):
            missing.append(f"{table}.{column}")
    return missing


def _has_column(conn, table: str, column: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass(%s) AND attname = %s", (table, column)
    ).fetchone() is not None


def _add_stems(conn) -> None:
    """Migration: stem existing chunks in place and rebuild the keyword index from the stems.

    Embeddings are untouched, so this costs no API calls and needs no re-upload.
    """
    if conn.execute("SELECT to_regclass('chunks')").fetchone()[0] is None or _has_column(conn, "chunks", "stems"):
        return
    with conn.transaction():
        conn.execute("ALTER TABLE chunks ADD COLUMN stems TEXT")
        rows = conn.execute("SELECT id, search_text FROM chunks").fetchall()
        with conn.cursor() as cur:
            cur.executemany("UPDATE chunks SET stems = %s WHERE id = %s", [(stem_text(text), id_) for id_, text in rows])
        conn.execute("ALTER TABLE chunks ALTER COLUMN stems SET NOT NULL")
        conn.execute("DROP INDEX IF EXISTS chunks_tsv_idx")
        conn.execute("ALTER TABLE chunks DROP COLUMN tsv")
        conn.execute("ALTER TABLE chunks ADD COLUMN tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', stems)) STORED")


def init_db() -> None:
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        missing = _missing_columns(conn)
        if missing:
            raise RuntimeError(
                f"The database schema is out of date (missing {', '.join(missing)}). Reset it with "
                "`docker compose exec db psql -U rag -d rag -c \"DROP TABLE chunks, documents\"` "
                "(cached embeddings are kept) and re-upload your documents."
            )
        existing = _existing_dim(conn)
        if existing is not None and existing != settings.embedding_dim:
            raise RuntimeError(
                f"The database stores {existing}-dimensional embeddings but EMBEDDING_DIM is "
                f"{settings.embedding_dim}. Switching embedding models needs a fresh database: "
                "run `docker compose down -v` and re-upload your documents."
            )
        _add_stems(conn)
        conn.execute(SCHEMA)
        if settings.embedding_dim <= HNSW_MAX_DIM:
            conn.execute(HNSW_INDEX)


def connect() -> psycopg.Connection:
    conn = psycopg.connect(settings.database_url, autocommit=True)
    register_vector(conn)
    return conn
