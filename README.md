# Legal RAG Assistant

A question-answering app over legal documents (laws, contracts, regulations) built on Retrieval-Augmented Generation. Upload PDF, DOCX or TXT files, ask questions in Serbian (Latin or Cyrillic) or English, and get answers grounded in the documents with numbered citations to the source passages.

**Stack:** Python, FastAPI, PostgreSQL + pgvector, any OpenAI-compatible LLM API (Google Gemini, OpenAI, Azure OpenAI, Ollama), Docker, n8n (custom TypeScript node)

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
- **Evaluation.** A 100-question harness (`scripts/harness.py`) scores retrieval, answers and citations with rule-based checks and an LLM judge, and gives each failure a root cause. `scripts/validate_data.py` checks the ingested documents for duplicates, missing fields and inconsistent dates.

## Evaluation

The evaluation harness (`scripts/harness.py`) runs a 100-question test set through the whole pipeline. For each question it scores retrieval, the answer and the citations, using both rule-based checks and an LLM judge, and gives every failure one root cause. `scripts/validate_data.py` checks the ingested documents themselves.

### Test set

`eval/testset.jsonl` has 100 questions over four documents: the Serbian Labour Law (Cyrillic PDF), two fictional job contracts, and a fictional annex to one of them.

| Category | Cases | What it tests |
|---|---|---|
| factual | 40 | One fact from the law |
| cyrillic | 4 | Question in Cyrillic |
| article | 6 | Names an article ("Šta propisuje član 62?"), including numbers that appear twice in the PDF |
| contract | 12 | One contract |
| comparison | 5 | Both contracts at once |
| conflict | 7 | Documents disagree: annex vs contract (salary, remote work, leave), contract vs law, a wrong date in the annex |
| ambiguous | 11 | Vague ("Koliko traje odmor?"), no diacritics, slang, English, or which contract is meant is not said |
| out_of_scope | 10 | Not in the documents, including near misses (net salary when only gross is given, a home address when only the city is) |
| false_premise | 5 | The question assumes something false ("Pošto zakon dozvoljava probni rad od godinu dana…") |

Each case lists the documents it is asked about (as if ticked in the UI), the phrase(s) the right passage contains, a reference answer (with grading notes where the right answer is "it depends"), and terms the answer must or must not contain. `--check` verifies that every expected phrase really exists in its documents, so a retrieval miss is never a typo in the test set. That check caught one mistake while I was building the set.

### What is scored

- **Retrieval:** does the top-k contain the expected passage(s)? Hit@k, recall and MRR, for all three search modes.
- **Rule-based checks:** required and forbidden terms (matched across scripts and with or without diacritics), refusal phrasing for unanswerable questions, whether a cited passage holds the expected text, citations to passages that don't exist, and numbers in the answer that appear in no retrieved passage (a cheap hallucination signal).
- **LLM judge:** a different model (`gemini-3.1-flash-lite`) than the one answering (`gemini-3.5-flash-lite`) decides whether the answer is *correct* against the reference and whether it is *grounded* in the retrieved passages. When the rules and the judge disagree, the report lists the case for a person to look at.
- **Root cause of each failure:** `missed_retrieval` (right passage not retrieved), `hallucination` (answered an unanswerable question, or stated something not in the passages), `wrong_citation` (right answer, wrong or missing citation), `false_abstention` (said "not found" although the passage was retrieved), `incomplete_answer`.

A case passes when the judge says correct and the answer cites the expected passage.

### Results

| | Baseline | After fixes |
|---|---|---|
| **Overall pass** | **91/100** | **98/100** |
| Answer accuracy (answerable) | 80/87 (92%) | 85/87 (98%) |
| Correct refusal (unanswerable) | 12/13 (92%) | 13/13 (100%) |
| Cites the expected passage | 84/87 (97%) | 87/87 (100%) |
| Grounded (judge) | 100% | 100% |
| Rules agree with judge | 89/94 | 93/94 |
| Retrieval Hit@5 / MRR (semantic) | 1.00 / 0.90 | 1.00 / 0.91 |

| Failure category | Baseline | After fixes |
|---|---|---|
| missed_retrieval | 0 | 0 |
| hallucination | 1 | 0 |
| wrong_citation | 1 | 0 |
| false_abstention | 3 | 1 |
| incomplete_answer | 4 | 1 |

Retrieval in the other modes, after fixes: keyword Hit@5 0.79 (MRR 0.62), hybrid 0.89 (MRR 0.75). Semantic stays the default.

By category after fixes, every category passes 100% except article (5/6) and false_premise (4/5). In the baseline, conflict (5/7) and ambiguous (8/11) were the weakest. Full reports: `eval/runs/baseline/report.md` and `eval/runs/final/report.md`; per-question answers and judge reasons are in each folder's `results.json`.

**Retrieval was never the problem:** semantic search found the right passage for all 87 answerable questions in both runs. Every failure happened after retrieval.

### What the failures showed, and what changed

| Baseline failure | Root cause | Fix |
|---|---|---|
| "Koliko dana godišnjeg odmora ima Ana Jović?" gave contract (22) and annex (18) side by side without saying which applies | incomplete_answer | Prompt: an annex changes the contract it amends; give its value as the one that applies |
| Contract-vs-law question, "Kolika je zarada?" over all documents, and a false premise ("which article gives 30 days of leave?") answered "I could not find it in the documents." in English | false_abstention | Prompt: answer per document when the question doesn't say which; correct a wrong premise; refuse only when no passage is relevant, and in the question's language |
| "Koliko traje probni rad?" over all documents answered only with the law's 6 months | incomplete_answer | Same per-document rule; now names both contracts and the law |
| "Koja je adresa stanovanja Nikole Ilića?" → "u Beogradu" | hallucination | Prompt: when only part of the answer is there, say what is missing, and never pass off a related fact (a city) as the one asked for (an address) |
| "Šta je uređeno članom 36?" summarised only part of the article | incomplete_answer | Article lookup now runs in semantic mode too, so a named article is always retrieved whole. **Still fails:** the full article is retrieved, but the summary leaves parts out |

Data validation also found two problems in how the law was ingested (below), and both are fixed: article 147 had been merged into article 146, and asking for an article by number could return a different article with the same number.

**Fixes to the evaluation itself**, kept separate so they aren't counted as system gains:
- The `wrong_citation` case (law-38) cited article 79, which answers the question more directly than the passage I had marked as expected. Both passages are now accepted.
- One reference answer (amb-08) asked for more than the question did.
- Three rule terms were too strict ("ana" doesn't match "Anu"), and the refusal detector didn't know "Ne mogao sam da pronađem". The judge was right every time; `--regrade` re-scores a saved run after a rule change without new LLM calls.

Of the 7 points gained, 5 come from system changes (cf-03, cf-06, amb-05, amb-09, oos-10) and 2 from fixing the evaluation (law-38, amb-08). Without the evaluation fixes the after-fixes score would be 96/100.

**Still failing (2):**
- fp-03, a false premise: the model still refuses instead of correcting it with the 20-day minimum.
- art-03: the summary of article 36 leaves out its durations.

Each run is a single pass of a free-tier lite model with temperature 0, so expect a point or two of noise between runs.

### Data validation

```bash
docker compose exec api python -m scripts.validate_data --out eval/data_validation.json
```

- **SQL checks** (`scripts/data_checks.sql`, one query per check, 14 in all):
  - duplicates: files, documents with identical text, near-duplicate documents, repeated chunks;
  - missing fields: documents without chunks, empty filenames or hashes, empty chunks, tiny chunks, PDF chunks without a page number;
  - structural problems: gaps in chunk numbering, page numbers going backwards, all-zero embeddings, cached embeddings from another model, upload times in the future.
- **Python checks:**
  - search text and stems out of sync with the chunk text;
  - dates that do not exist (31.02.);
  - contracts and annexes missing key fields (signing date, start date, parties, PIB, position, salary);
  - dates in the wrong order (start before signing, annex signed before its contract);
  - an annex pointing at a contract date that doesn't exist;
  - one employer appearing with two PIBs;
  - contract terms outside the Labour Law's limits (leave under 20 days, probation over 6 months, fixed term over 24 months, employee notice outside 15–30 days);
  - gaps and repeats in a law's article numbering.

The script exits with status 1 on any error, so it can gate CI or a bulk ingest. `tests/test_validate_data.py` plants every kind of SQL problem in a rolled-back transaction to prove each check fires.

Findings on the current index:

| Finding | Severity | What it was | Action |
|---|---|---|---|
| `article_gaps`: article 147 never starts a chunk | warning | The PDF heading is `Члан 147. *` (space before the footnote asterisk), which the chunker didn't recognise, so article 147 was merged into 146 | Chunker fixed. The original PDF wasn't available, so `scripts/rechunk.py` rebuilt the document from its stored chunks: 1 chunk became 2, the other 383 came back identical, and only 2 new embeddings were computed. The warning is gone |
| `repeated_article`: articles 11–13 and 110–119 start two chunks each | warning | The consolidated text ends with transitional articles of the amending laws, which reuse those numbers. "član 110" returned both | Article lookup keeps the law's own article. Regression cases art-05 and art-06 were added. The warning stays, because the data really does contain both |
| `conflicts_with_law`: annex gives 18 days of annual leave | error | Planted in the fictional annex on purpose | Kept on purpose: test cases cf-03 and cf-04 rely on it |
| `annex_date_mismatch`: annex amends "the contract of 15.03.2025", the contract is dated 15.03.2026 | error | Planted on purpose | Kept on purpose: test case cf-07 relies on it |

All 14 SQL checks pass on the real data (no duplicates, missing fields or broken numbering).

### Running the evaluation

```bash
docker compose exec api python -m scripts.harness eval/testset.jsonl --check            # test set vs index, no LLM calls
docker compose exec api python -m scripts.harness eval/testset.jsonl --retrieval-only   # all search modes, no chat calls
docker compose exec api python -m scripts.harness eval/testset.jsonl --judge-model gemini-3.1-flash-lite --out eval/runs/latest
```

`--resume` continues after a free-tier quota stop. `--only cf-01 ambiguous` runs only some cases or categories. A full run makes about 200 chat calls, which takes roughly 20–40 minutes on the Gemini free tier. The run behind these numbers needs the annex indexed too: `curl -F "file=@samples/aneks_ugovora_ana_jovic.txt" http://localhost:8000/documents`.

The original smaller evaluation (`eval/questions.jsonl` with `scripts/evaluate.py` and `scripts/evaluate_answers.py`, 28 questions about the law only) still works. These findings from it still hold:
- Transliteration took retrieval on the Cyrillic PDF from 0.00 to 1.00.
- Handling footnote asterisks and keeping article numbers in keyword search improved results.
- A light Serbian stemmer took hybrid Hit@5 from 0.92 to 0.96.
- Remaining keyword misses are vocabulary mismatches, which is why semantic search is the default.

## n8n integration

The assistant also runs inside [n8n](https://n8n.io/) workflows through a custom community node, [`n8n-nodes-legal-rag`](n8n-nodes-legal-rag/) (TypeScript).

- **Node:** Ask (answer + `answered` flag + only the cited passages), Search passages, and Upload / list / delete documents, with a document dropdown loaded from the API. It also works as an AI Agent tool. It passes n8n's strict community-node lint, so it qualifies for n8n Cloud verification. Details are in its [README](n8n-nodes-legal-rag/README.md).
- **API changes it needed:**
  - `/ask` returns `answered` and `citations`, so workflows can route unanswered questions to a person without parsing text. The evaluation harness uses the same refusal rule.
  - An optional `API_KEY` (sent as `X-API-Key`) protects the API once something on the network calls it.
- **Example workflows** ([`n8n-nodes-legal-rag/examples/`](n8n-nodes-legal-rag/examples/)), tested on n8n 2.43.7:
  - **Q&A webhook:** POST a question, get a cited answer as JSON; errors return 422.
  - **Email → draft → Slack review → reply:** an approved draft is emailed back; an unanswered question goes to an escalation channel.
  - **Contract intake form → checklist → Google Sheet:** an uploaded contract is indexed and its key terms are extracted into a row.

### Self-hosted n8n

Both the API and n8n run on my Ubuntu 26.04 home server, next to the other services there:

| Service | Compose | Notes |
|---|---|---|
| n8n 2.43.7 (pinned) + Postgres 17 | [`deploy/n8n/`](deploy/n8n/) | Credentials encrypted with a generated `N8N_ENCRYPTION_KEY`; the community node persists in the `n8n-data` volume |
| Legal RAG API + Postgres/pgvector | `docker-compose.yml` + [`docker-compose.server.yml`](docker-compose.server.yml) | Database not published to the host; `API_KEY` required; restarts on boot |

Both join the `nginx-net` network that Nginx Proxy Manager uses, so n8n calls the API by container name (`http://legal-rag-api:8000`) and the API never has to be exposed beyond the LAN for n8n's sake.

```bash
# n8n
cd deploy/n8n && cp .env.example .env   # fill in the two secrets: openssl rand -hex 32
docker compose -f docker-compose.yml -f docker-compose.nginx-net.yml up -d

# API (same .env as local, plus API_KEY)
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
```

The server's index was moved over with `pg_dump -Fc` / `pg_restore` (4 documents, 413 chunks, 1,063 cached embeddings), so nothing was re-embedded. Without the server override (one machine, n8n and API in separate compose projects), use `http://host.docker.internal:8000` as the credential's base URL.

### Node, workflow, or push back: what I'd do differently

**Why this is a node.** Every workflow that talks to this API needs the same things: the auth header, multipart upload from binary data, a re-upload that doesn't fail, citations matched to passages, and a reliable "was this answered?" signal. With the HTTP Request node, each workflow would rebuild that logic, slightly differently each time. A node does it once, gives a dropdown of documents instead of raw ids, and becomes an AI Agent tool for free. That's the test I'd apply at a customer: build a node when **several workflows need the same integration logic**, not just when there's an API.

**What stays in the workflow.** The contract checklist (which five terms, the questions, the sheet columns), Slack channel names, the approval step and the 2-day timeout are all specific to one customer's process. I kept them in the workflows (a Code node, the Slack node), not as node parameters, and deliberately did *not* add an "Extract contract terms" operation. A node with one customer's checklist baked in isn't reusable, and a workflow is something the customer can edit without a release.

**What moved to the server instead.** The "answered" check started as node logic and moved into the API, so the web UI, the node and the evaluation harness all use one rule. If the logic is about the data, it belongs behind the API, not in the integration.

**Where I'd push back:**
- *"Auto-reply to legal emails."* No. The model drafts and a person approves in Slack. Unanswered and partly answered questions go to a person. The evaluation shows 98% accuracy, which means about 1 in 50 answers would still be wrong.
- *"Make it a trigger node (new document indexed)."* Not yet. The API has no events, so a trigger would just be a polling loop dressed up as one. Add webhooks to the API first.
- *"Build our own RAG for this."* Only if it earns it. For English PDFs and simple questions, n8n's built-in vector store and AI Agent nodes are enough and easier for a customer to own. A separate service pays off here because of Serbian Cyrillic/Latin handling, article-aware chunking, scoping by document, and an evaluation set that proves the answers are right.

**What I'd do differently next time:**
- In a real engagement I'd start with an HTTP Request node prototype of the main workflow, confirm it's the right workflow with the users, and only then turn it into a node. Here the node was the goal from the start.
- Test the email and Slack paths against the customer's real systems on day one. I could only test them against a local mail server, with the Slack and SMTP nodes disabled.
- Put n8n behind HTTPS (Nginx Proxy Manager is already on the server), then turn secure cookies back on.

**Feedback I'd pass to n8n's product team**, from building this:
- The documented manual install of a community node in Docker fails unless you add `--legacy-peer-deps`.
- The strict community-node lint also applies to test files, so even `node:test` imports fail it. Tests have to be written as `.mjs` to get around it.

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

Set `API_KEY` in `.env` before anything else on the network (such as n8n) calls the API; clients then send it as `X-API-Key`, and the web page asks for it once.

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
| `POST` | `/ask` | Answer a question with cited sources, `answered` and `citations`, token usage and timings; optional `documents` limits it to those ids |
| `GET` | `/info` | Active provider and models |
| `GET` | `/health` | Health check |

### Sample documents

`samples/` holds two fictional job contracts (different salary, probation, leave, remote work) and an annex that amends one of them, for per-document and conflicting-document questions. The annex contains two deliberate defects (leave below the legal minimum, a wrong contract date) that data validation must catch.

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
  main.py      FastAPI routes, optional API key, error handling
  ingest.py    Text extraction (PDF, DOCX, TXT), page joining, duplicate detection, indexing
  chunking.py  Article-aware chunking
  text.py      Cyrillic → Latin transliteration and search normalisation
  stemmer.py   Light Serbian stemmer for keyword search
  llm.py       OpenAI-compatible client, rate limiting, cached embeddings, chat
  search.py    Semantic, keyword (article lookup + full-text) and hybrid (RRF) retrieval
  rag.py       Prompt construction and answer generation
  db.py        Schema (pgvector, full-text GIN index) and schema checks
  static/      Web UI (single page, no build step)
scripts/       Bulk ingest, re-chunking, evaluation harness, data validation (+ data_checks.sql)
eval/          Test set (testset.jsonl), harness runs (runs/), data-validation findings, original eval
samples/       Two fictional job contracts and an annex to one of them
tests/         Unit tests (chunking, transliteration, stemming, search, rate limiting, page mapping, grading, harness, data checks, API key)
n8n-nodes-legal-rag/  n8n community node (TypeScript), its tests and example workflows
deploy/n8n/    Self-hosted n8n (Docker Compose, Postgres 17)
docker-compose.server.yml  Server override: private database, restart policy, shared proxy network
.github/       CI and npm publishing for the n8n node
```

## Roadmap

- Cross-encoder re-ranking of retrieved candidates
- Questions spanning several articles; repeated runs to measure judge and model variance
- Streaming responses
- Webhooks from the API (document indexed, answer flagged), so n8n can use real triggers instead of polling
- Contract-specific extraction (parties, salary, dates) for structured comparisons
