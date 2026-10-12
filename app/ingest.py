import hashlib
from bisect import bisect_right
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader

from app import llm
from app.chunking import chunk_document, normalize
from app.config import settings
from app.stemmer import stem_text
from app.text import for_search

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}


class DuplicateDocumentError(Exception):
    def __init__(self, filename: str, document_id: int):
        super().__init__(f"This file is already indexed as '{filename}' (document {document_id}).")


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


def join_pages(pages: list[tuple[int | None, str]]) -> tuple[str, list[int], list[int | None]]:
    """Join pages into one text so articles that cross a page break stay together.

    Returns the text plus each page's start offset and number, to map a chunk back to its page.
    """
    parts, starts, numbers, offset = [], [], [], 0
    for number, text in pages:
        text = normalize(text)
        if not text:
            continue
        starts.append(offset)
        numbers.append(number)
        parts.append(text)
        offset += len(text) + 2  # the "\n\n" separator
    return "\n\n".join(parts), starts, numbers


def ingest_file(conn, path: Path, filename: str | None = None) -> dict:
    filename = filename or path.name
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    existing = conn.execute("SELECT id, filename FROM documents WHERE file_hash = %s", (file_hash,)).fetchone()
    if existing:
        raise DuplicateDocumentError(existing[1], existing[0])

    text, page_starts, page_numbers = join_pages(extract_pages(path))
    chunks = chunk_document(text, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        raise ValueError(f"No text could be extracted from {filename}")
    pages = [page_numbers[bisect_right(page_starts, c.start) - 1] for c in chunks]

    search_texts = [for_search(c.text) for c in chunks]
    embeddings, stats = llm.embed_texts(conn, search_texts)

    with conn.transaction():
        document_id = conn.execute(
            "INSERT INTO documents (filename, file_hash) VALUES (%s, %s) RETURNING id", (filename, file_hash)
        ).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (document_id, chunk_index, page, content, search_text, stems, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (document_id, i, page, chunk.text, search_text, stem_text(search_text), emb)
                    for i, (chunk, page, search_text, emb) in enumerate(zip(chunks, pages, search_texts, embeddings))
                ],
            )

    return {
        "document_id": document_id,
        "filename": filename,
        "chunks": len(chunks),
        "embeddings_cached": stats.cached,
        "embeddings_computed": stats.computed,
        "embedding_tokens": stats.tokens,
    }
