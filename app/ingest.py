from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader

from app import llm
from app.chunking import chunk_document
from app.config import settings

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}


def extract_pages(path: Path) -> list[tuple[int | None, str]]:
    """Return (page number, text) pairs. Formats without pages yield a single (None, text) pair."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(path)
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    if suffix == ".docx":
        return [(None, "\n".join(p.text for p in DocxDocument(path).paragraphs))]
    if suffix in (".txt", ".md"):
        return [(None, path.read_text(encoding="utf-8"))]
    raise ValueError(f"Unsupported file type: {suffix}")


def ingest_file(conn, path: Path, filename: str | None = None) -> dict:
    filename = filename or path.name
    pieces: list[tuple[int | None, str]] = []
    for page, text in extract_pages(path):
        for chunk in chunk_document(text, settings.chunk_size, settings.chunk_overlap):
            pieces.append((page, chunk))
    if not pieces:
        raise ValueError(f"No text could be extracted from {filename}")

    embeddings, stats = llm.embed_texts(conn, [text for _, text in pieces])

    with conn.transaction():
        document_id = conn.execute(
            "INSERT INTO documents (filename) VALUES (%s) RETURNING id", (filename,)
        ).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (document_id, chunk_index, page, content, embedding) "
                "VALUES (%s, %s, %s, %s, %s)",
                [
                    (document_id, i, page, text, emb)
                    for i, ((page, text), emb) in enumerate(zip(pieces, embeddings))
                ],
            )

    return {
        "document_id": document_id,
        "filename": filename,
        "chunks": len(pieces),
        "embeddings_cached": stats.cached,
        "embeddings_computed": stats.computed,
        "embedding_tokens": stats.tokens,
    }
