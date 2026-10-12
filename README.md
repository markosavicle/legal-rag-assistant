# Legal RAG Assistant

A question-answering app over legal documents (laws, contracts, regulations) built on Retrieval-Augmented Generation. Upload PDF, DOCX or TXT files, ask questions in Serbian (Latin or Cyrillic) or English, and get answers grounded in the documents with numbered citations to the source passages.

**Stack:** Python, FastAPI, PostgreSQL + pgvector, any OpenAI-compatible LLM API (Google Gemini, OpenAI, Azure OpenAI, Ollama), Docker

## How it works

```
upload ─► extract text ─► join pages ─► split by article (Član N) ─► chunk ─► normalise ─► embed (cached) ─► Postgres
                                                                                                              │
question ─► normalise ─┬─► semantic search (pgvector, cosine similarity) ──┐                                   │
                       └─► keyword search (article lookup + full-text) ────┴─► one mode, or fused (RRF) ─► top-k chunks
                                                                                                              │
                                                        LLM with grounded prompt ─► answer with [n] citations ◄┘
```

- **Legal-aware chunking.** The whole document is split on article headings (`Član N` / `Члан N`, including amended `Član 111.*`) before anything else, so a chunk never mixes two articles, and an article that crosses a page break stays together. Long articles are cut into ~800-character chunks with 150 characters of overlap at paragraph or sentence boundaries, and every continuation chunk is labelled `Član N (nastavak)`.
- **Cyrillic and Latin.** The official Zakon o radu PDF is Cyrillic. Text is transliterated to Latin and stripped of amendment footnote asterisks (`dve* prosečne zarade`) for embeddings and search only, so a question in either script finds a document in either script, while sources are still shown in the original.
- **Three search modes.** Semantic search finds passages with similar meaning. Keyword search first looks up any article the question names ("član 62", "članom 36"), then runs Postgres full-text search over **stemmed** text: a light Serbian stemmer (`app/stemmer.py`) reduces odmor/odmora/odmoru to one form and folds diacritics, so "godisnji" matches "godišnji". Hybrid merges both rankings with Reciprocal Rank Fusion.
- **Ask about specific documents.** Every search can be limited to chosen documents: tick documents in the UI (or click *Only*), or pass `"documents": [ids]` to `/ask`. With two job contracts uploaded, "Kolika je zarada?" answers for one contract, or compares both when both are selected.
- **Grounded answers.** The model may only use the retrieved passages, must cite them as `[n]`, must answer in the question's script, and must say so when the answer is not in the documents.
- **Cost control.** Embeddings are cached in Postgres by content hash, so re-indexing unchanged text costs nothing. Uploading the same file twice is rejected. Requests are paced to stay within free-tier per-minute quotas. Every answer reports token usage and how long search and generation took.
- **Evaluation.** `scripts/evaluate.py` measures whether search finds the right passage; `scripts/evaluate_answers.py` measures whether the final answers are correct, cite the right passage, and decline out-of-scope questions.

## Evaluation

`eval/questions.jsonl` holds 28 questions about the Serbian Labour Law: 20 everyday questions, 2 in Cyrillic, 3 that name an article number, and 3 the law does not cover. Each in-scope question has a phrase the correct passage must contain and a reference answer.

### Retrieval: does search find the right passage?

| Mode | Hit@5 | MRR |
|---|---|---|
| **Semantic** | **1.00** | **0.98** |
| Keyword | 0.84 | 0.66 |
| Hybrid | 0.96 | 0.88 |

*Hit@5:* share of questions where the right passage is among the 5 retrieved. *MRR:* average of 1 / rank of the first right passage (1.00 = always first).

What the numbers showed, and what changed because of them:

- The first run on the real law scored **0.00**: the PDF is Cyrillic and the pipeline only handled Latin. Transliteration fixed it.
- Footnote asterisks in headings (`Član 111.*`) merged neighbouring articles and broke phrase matching. They are now handled.
- Keyword search dropped short tokens, including article numbers like "62". It now keeps numbers and looks named articles up directly (keyword Hit@5 0.76 → 0.88).
- Postgres has no Serbian stemmer, so keyword search missed inflected forms (odmor/odmora). A light Serbian stemmer lifted hybrid from 0.92 to 0.96. Keyword search alone stayed around 0.84–0.88; IDF-weighted (BM25-style) ranking was tried and didn't help.
- The remaining keyword misses are vocabulary mismatches no word-matching can fix: "odmor **između dva radna dana**" is answered by an article that says "u okviru 24 časa". That is what semantic search is for, so **semantic is the default mode**. Hybrid and keyword stay available in the UI and API.

### Answers: is the final answer right?

`scripts/evaluate_answers.py` runs the full pipeline for every question and checks:

- **Answer accuracy:** an LLM judge compares the answer with the reference answer. The judge is a different model (`gemini-3.1-flash-lite`) than the one answering (`gemini-3.5-flash-lite`), so a model never grades itself.
- **Citation accuracy:** deterministic. At least one passage the answer cites with `[n]` must contain the expected phrase.
- **Abstention:** for the 3 out-of-scope questions (speeding fines, VAT, car registration), the system must say it could not find the answer.

| Check | Result |
|---|---|
| Answer accuracy | 24/25 (96%) |
| Citation accuracy | 25/25 (100%) |
| Abstention (out-of-scope) | 3/3 (100%) |
| Average time per answer | 2.7 s |

The one wrong answer was a summary question ("Šta je uređeno članom 36?"): the answer covered probation and its maximum length but left out the minimum notice period. Per-question results, answers and the judge's reasons are in `eval/answer_results.json`.

The first run scored 23/25 on citations and found two real problems: the lite model sometimes wrote citations as `[1, 2]` (not parsed by the UI) or none at all, and mixed Cyrillic into Latin answers. The prompt now requires a citation on every sentence, both the UI and the checker accept `[1, 2]`, and Latin questions get their answer converted to Latin in code (Serbian Cyrillic → Latin is exact, so this is guaranteed rather than hoped for).

```bash
docker compose exec api python -m scripts.evaluate_answers eval/questions.jsonl     --document "Zakon o radu.pdf" --judge-model gemini-3.1-flash-lite --out eval/answer_results.json
```

Retrieval evaluation (add `--misses` to list the questions each mode got wrong):

```bash
docker compose exec api python -m scripts.evaluate eval/questions.jsonl --document "Zakon o radu.pdf" --misses
```

## Running it

```bash
cp .env.example .env          # pick a provider and add its key (see below)
docker compose up --build
```

- Web app: http://localhost:8000 (upload documents, ask questions, inspect cited sources, compare search modes)
- API docs: http://localhost:8000/docs

### AI providers

The app talks to any OpenAI-compatible API, so switching provider is a `.env` change:

| Provider | Cost | Notes |
|---|---|---|
| Google Gemini | Free tier | Key from [AI Studio](https://aistudio.google.com/apikey). Default in `.env.example`. Requests are paced to the free per-minute limits; daily limits differ per model (gemini-3.5-flash: 20 a day, the lite models far more), which is why the default chat model is a lite one. |
| Ollama | Free, local | No key, runs on your machine. Good for offline or private documents. |
| OpenAI | Paid | `text-embedding-3-small` + `gpt-4o-mini` |
| Azure OpenAI | Paid | Uses deployment names |

Embeddings from different models aren't comparable, so switching the embedding model needs a fresh database (`docker compose down -v`). The app refuses to start with a clear message if the configured dimension doesn't match the stored one.

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
| `POST` | `/documents` | Upload and index a PDF, DOCX, TXT or MD file (409 if already indexed) |
| `GET` | `/documents` | List indexed documents |
| `DELETE` | `/documents/{id}` | Remove a document and its chunks |
| `GET` | `/search?q=&k=&mode=&documents=` | Retrieval only (`vector`, `keyword`, `hybrid`) |
| `POST` | `/ask` | Answer a question with cited sources, token usage and timings; optional `documents` limits it to those ids |
| `GET` | `/info` | Active provider and models |
| `GET` | `/health` | Health check |

### Sample documents

`samples/` holds two fictional job contracts (different salary, probation, leave, remote work) for trying per-document questions.

### Bulk ingest

```bash
docker compose exec api python -m scripts.ingest_dir data
```

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
  main.py      FastAPI routes and error handling
  ingest.py    Text extraction (PDF, DOCX, TXT), page joining, duplicate detection, indexing
  chunking.py  Article-aware chunking
  text.py      Cyrillic → Latin transliteration and search normalisation
  stemmer.py   Light Serbian stemmer for keyword search
  llm.py       OpenAI-compatible client, rate limiting, cached embeddings, chat
  search.py    Semantic, keyword (article lookup + full-text) and hybrid (RRF) retrieval
  rag.py       Prompt construction and answer generation
  db.py        Schema (pgvector, full-text GIN index) and schema checks
  static/      Web UI (single page, no build step)
scripts/       Bulk ingest, retrieval evaluation, answer evaluation
eval/          Evaluation questions with reference answers, and the latest answer results
samples/       Two fictional job contracts
tests/         Unit tests (chunking, transliteration, stemming, search, rate limiting, page mapping, grading)
```

## Roadmap

- Cross-encoder re-ranking of retrieved candidates
- A larger evaluation set, including questions spanning several articles
- Streaming responses
- Contract-specific extraction (parties, salary, dates) for structured comparisons
