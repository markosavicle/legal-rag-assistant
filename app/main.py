import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import openai
from fastapi import FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app import db, rag
from app.config import settings
from pypdf.errors import PdfReadError

from app.ingest import SUPPORTED, DuplicateDocumentError, ingest_file
from app.llm import embed_query, is_daily_quota, provider_name
from app.search import search

Mode = Literal["vector", "keyword", "hybrid"]

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Legal RAG Assistant", lifespan=lifespan)


@app.exception_handler(openai.APIError)
def ai_provider_error(_: Request, exc: openai.APIError):
    # Surface provider problems (bad key, rate limit, unknown model) instead of a bare 500.
    status = getattr(exc, "status_code", None) or 502
    if is_daily_quota(exc):
        detail = (f"The free daily quota for this model is used up (it resets within a day). "
                  f"Set CHAT_MODEL in .env to another model, e.g. a '-lite' one, and restart. Details: {exc.message}")
    else:
        detail = f"AI provider error ({status}): {exc.message}"
    return JSONResponse(status_code=502, content={"detail": detail})


@app.get("/", include_in_schema=False)
def web_ui():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/info")
def info():
    return {
        "provider": provider_name(),
        "chat_model": settings.chat_model,
        "embedding_model": settings.embedding_model,
        "top_k": settings.top_k,
        "supported_files": sorted(SUPPORTED),
    }


class AskRequest(BaseModel):
    question: str = Field(min_length=3)
    k: int = Field(default=settings.top_k, ge=1, le=20)
    # Semantic search scored best on eval/questions.jsonl (see README), so it is the default.
    mode: Mode = "vector"
    # Limit the question to these documents, e.g. one of two contracts. None or empty = all documents.
    documents: list[int] | None = None


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
        except DuplicateDocumentError as e:
            raise HTTPException(409, str(e))
        except (ValueError, PdfReadError) as e:
            raise HTTPException(422, f"Could not read {file.filename}: {e}")


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
def search_chunks(
    q: str = Query(min_length=2),
    k: int = Query(settings.top_k, ge=1, le=50),
    mode: Mode = "vector",
    documents: list[int] | None = Query(None, description="Document ids to search (repeat the parameter); all if omitted"),
):
    with db.connect() as conn:
        query_embedding = embed_query(conn, q) if mode != "keyword" else None
        return search(conn, q, query_embedding, k, mode, documents)


@app.post("/ask")
def ask(request: AskRequest):
    with db.connect() as conn:
        return rag.answer(conn, request.question, request.k, request.mode, request.documents or None)
