# Legal RAG Assistant

A question-answering API over legal documents (laws, contracts, regulations) built on Retrieval-Augmented Generation. Upload PDF, DOCX or TXT files, ask questions in Serbian or English, and get answers grounded in the documents with numbered citations to the source passages.

**Stack:** Python, FastAPI, PostgreSQL + pgvector, OpenAI / Azure OpenAI, Docker

## How it works

```
upload ─► extract text ─► split by article (Član N) ─► chunk ─► embed (cached) ─► Postgres + pgvector
                                                                                      │
question ─► embed ─► vector search (pgvector, cosine) ──┐                             │
          └──────► keyword search (Postgres full-text) ─┴─► Reciprocal Rank Fusion ─► top-k chunks
                                                                                      │
                                              LLM with grounded prompt + citations ◄──┘
```

- **Legal-aware chunking.** Serbian laws are split on `Član N` headings first, so a chunk never mixes two articles. Long articles are cut into ~800-character chunks with overlap, preferring paragraph and sentence boundaries.
- **Hybrid search.** Vector search finds passages with similar meaning; full-text search catches exact terms (article numbers, defined legal terms) that embeddings can miss. The two rankings are merged with Reciprocal Rank Fusion.
- **Grounded answers.** The model may only use the retrieved passages, must cite them as `[n]`, and must say so when the answer is not in the documents.
- **Cost control.** Embeddings are cached in Postgres by content hash, so re-uploading or re-indexing unchanged text costs zero tokens. Every `/ask` response reports token usage and latency.
- **Evaluation.** `scripts/evaluate.py` measures Hit@k and MRR for vector, keyword and hybrid retrieval on a labelled question set.

## Running it

```bash
cp .env.example .env          # add OPENAI_API_KEY (or the Azure OpenAI settings)
docker compose up --build
```

API docs: http://localhost:8000/docs

```bash
# Upload a document
curl -F "file=@data/zakon_o_radu.pdf" http://localhost:8000/documents

# Ask a question
curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" \
     -d '{"question": "Koliko najmanje traje godišnji odmor?"}'

# Inspect retrieval only, per mode
curl "http://localhost:8000/search?q=probni%20rad&mode=hybrid"
```

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/documents` | Upload and index a PDF, DOCX, TXT or MD file |
| `GET` | `/documents` | List indexed documents |
| `DELETE` | `/documents/{id}` | Remove a document and its chunks |
| `GET` | `/search?q=&k=&mode=` | Retrieval only (`vector`, `keyword`, `hybrid`) |
| `POST` | `/ask` | Answer a question with cited sources, token usage and latency |
| `GET` | `/health` | Health check |

### Bulk ingest and evaluation

```bash
docker compose exec api python -m scripts.ingest_dir data
docker compose exec api python -m scripts.evaluate eval/questions.jsonl --k 5
```

`eval/questions.jsonl` holds questions about the Serbian Labour Law (Zakon o radu) with a phrase the correct passage must contain.

## Development

```bash
python -m venv .venv && .venv/Scripts/activate   # source .venv/bin/activate on Linux/macOS
pip install -r requirements.txt
docker compose up -d db
pytest
uvicorn app.main:app --reload
```

## Project layout

```
app/
  main.py      FastAPI routes
  chunking.py  Article-aware text chunking
  ingest.py    Text extraction (PDF, DOCX, TXT) and indexing
  llm.py       OpenAI / Azure OpenAI client, cached embeddings, chat
  search.py    Vector, keyword and hybrid (RRF) retrieval
  rag.py       Prompt construction and answer generation
  db.py        Schema (pgvector HNSW index, full-text GIN index)
scripts/       Bulk ingest and retrieval evaluation
tests/         Unit tests for chunking, fusion and prompt building
```

## Roadmap

- Cross-encoder re-ranking of the fused candidates
- Local open-source models (embeddings and chat) as an alternative to OpenAI
- Streaming responses
- Speech-to-text input for spoken questions
