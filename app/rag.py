import re
import time

from app import llm
from app.search import Hit, search
from app.text import to_latin

SYSTEM_PROMPT = """You are an assistant for questions about legal documents.
Answer ONLY using the numbered context passages provided by the user.
End every sentence with the number of the passage it comes from, in square brackets, e.g. [2].
For several passages write [1][3], not [1, 3].
Each passage is labelled with its document. When passages come from several documents:
- If the question does not say which document or person it means, answer for each relevant document separately and name it.
- If the documents disagree, say so. An annex (aneks) changes the contract it amends: give the annex's value as the one that applies, and mention the original.
- If a contract gives an employee less than the law requires, say so.
If the question assumes something the passages contradict, correct it using the passages.
If the passages answer only part of the question, give that part and say what is missing. Never present a related fact (a city) as the requested one (an address).
Only if no passage is relevant, say that you could not find the answer in the documents. Do not guess.
Answer in the same language and script (Latin or Cyrillic) as the question, even if the passages use the other script; this includes saying that you could not find the answer."""

CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def match_script(question: str, answer: str) -> str:
    """Models sometimes copy Cyrillic passages into a Latin answer. Serbian Cyrillic converts to
    Latin exactly, so a Latin question always gets a fully Latin answer. (Latin to Cyrillic is
    ambiguous, e.g. "nj", so Cyrillic questions rely on the prompt.)"""
    return answer if CYRILLIC.search(question) else to_latin(answer)


def format_source(hit: Hit) -> str:
    location = f", page {hit.page}" if hit.page else ""
    return f"{hit.filename}{location}"


def build_messages(question: str, hits: list[Hit]) -> list[dict]:
    context = "\n\n".join(
        f"[{i}] ({format_source(hit)})\n{hit.content}" for i, hit in enumerate(hits, start=1)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
    ]


def answer(conn, question: str, k: int, mode: str = "vector", documents: list[int] | None = None) -> dict:
    started = time.perf_counter()
    query_embedding = llm.embed_query(conn, question) if mode != "keyword" else None
    hits = search(conn, question, query_embedding, k, mode, documents)
    retrieved = time.perf_counter()

    if not hits:
        text, usage = "I could not find anything relevant in the uploaded documents.", {}
    else:
        text, usage = llm.chat(build_messages(question, hits))
        text = match_script(question, text)
    finished = time.perf_counter()

    return {
        "answer": text,
        "sources": [
            {"n": i, "source": format_source(h), "chunk_id": h.chunk_id, "score": round(h.score, 4), "text": h.content}
            for i, h in enumerate(hits, start=1)
        ],
        "usage": usage,
        "latency_ms": round((finished - started) * 1000),
        "retrieval_ms": round((retrieved - started) * 1000),
        "generation_ms": round((finished - retrieved) * 1000),
    }
