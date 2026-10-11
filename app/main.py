import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app import db, rag
from app.config import settings
from app.ingest import SUPPORTED, ingest_file
from app.llm import embed_query
from app.search import search

Mode = Literal["vector", "keyword", "hybrid"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Legal RAG Assistant", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(min_length=3)
    k: int = Field(default=settings.top_k, ge=1, le=20)
    mode: Mode = "hybrid"


@app.get("/health")
def health():
    with db.connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/documents", status_code=201)
def upload_document(file: UploadFile):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Supported: {sorted(SUPPORTED)}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        with path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            with db.connect() as conn:
                return ingest_file(conn, path, file.filename)
        except ValueError as e:
            raise HTTPException(422, str(e))


@app.get("/documents")
def list_documents():
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT d.id, d.filename, d.created_at, count(c.id) FROM documents d "
            "LEFT JOIN chunks c ON c.document_id = d.id GROUP BY d.id ORDER BY d.id"
        ).fetchall()
    return [{"id": r[0], "filename": r[1], "created_at": r[2], "chunks": r[3]} for r in rows]


@app.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int):
    with db.connect() as conn:
        if conn.execute("DELETE FROM documents WHERE id = %s", (document_id,)).rowcount == 0:
            raise HTTPException(404, "Document not found")


@app.get("/search")
def search_chunks(q: str = Query(min_length=2), k: int = Query(settings.top_k, ge=1, le=50), mode: Mode = "hybrid"):
    with db.connect() as conn:
        query_embedding = embed_query(conn, q) if mode != "keyword" else None
        return search(conn, q, query_embedding, k, mode)


@app.post("/ask")
def ask(request: AskRequest):
    with db.connect() as conn:
        return rag.answer(conn, request.question, request.k, request.mode)
