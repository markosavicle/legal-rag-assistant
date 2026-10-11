import time

from app import llm
from app.search import Hit, search

SYSTEM_PROMPT = """You are an assistant for questions about legal documents.
Answer ONLY using the numbered context passages provided by the user.
Cite every claim with the passage number in square brackets, e.g. [2].
If the context does not contain the answer, say that you could not find it in the documents. Do not guess.
Answer in the same language as the question."""


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


def answer(conn, question: str, k: int, mode: str = "hybrid") -> dict:
    started = time.perf_counter()
    query_embedding = llm.embed_query(conn, question) if mode != "keyword" else None
    hits = search(conn, question, query_embedding, k, mode)

    if not hits:
        text, usage = "I could not find anything relevant in the uploaded documents.", {}
    else:
        text, usage = llm.chat(build_messages(question, hits))

    return {
        "answer": text,
        "sources": [
            {"n": i, "source": format_source(h), "chunk_id": h.chunk_id, "score": round(h.score, 4), "excerpt": h.content[:300]}
            for i, h in enumerate(hits, start=1)
        ],
        "usage": usage,
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }
