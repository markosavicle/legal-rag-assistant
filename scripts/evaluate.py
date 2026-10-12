"""Measure retrieval quality for each search mode (did search find the right passage?).

See evaluate_answers.py for whether the final answers are correct.

Each line of the eval file is {"question": ..., "expected": ...}, where `expected` is a short
phrase that appears in the passage that answers the question. A retrieved chunk counts as
relevant when it contains that phrase (case-insensitive).

Reports Hit@k (did any of the top k chunks contain the answer?) and MRR
(mean of 1 / rank of the first relevant chunk).

Usage: python -m scripts.evaluate eval/questions.jsonl --k 5
"""
import argparse
import json
import time
from pathlib import Path

from app import db
from app.llm import embed_query
from app.search import MODES, search
from app.text import for_search


def comparable(text: str) -> str:
    # Latin script, no footnote marks, single spaces, so phrases match across scripts and line breaks.
    return " ".join(for_search(text).lower().split())


def first_relevant_rank(hits, expected: str) -> int | None:
    needle = comparable(expected)
    for rank, hit in enumerate(hits, start=1):
        if needle in comparable(hit.content):
            return rank
    return None


def document_ids(conn, filenames: list[str] | None) -> list[int] | None:
    """Ids of the named documents, to evaluate against one document when several are indexed."""
    if not filenames:
        return None
    rows = conn.execute("SELECT id, filename FROM documents WHERE filename = ANY(%s)", (filenames,)).fetchall()
    missing = set(filenames) - {name for _, name in rows}
    if missing:
        raise SystemExit(f"Not indexed: {', '.join(sorted(missing))}")
    return [id_ for id_, _ in rows]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("eval_file")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--misses", action="store_true", help="list the questions each mode got wrong")
    parser.add_argument("--document", action="append", help="only search this document (filename; repeatable)")
    args = parser.parse_args()

    cases = [json.loads(line) for line in Path(args.eval_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    # Out-of-scope questions (no expected passage) are only used by evaluate_answers.py.
    cases = [c for c in cases if c.get("expected")]

    with db.connect() as conn:
        documents = document_ids(conn, args.document)
        embeddings = [embed_query(conn, c["question"]) for c in cases]
        print(f"{len(cases)} questions, k={args.k}\n")
        print(f"{'mode':<10}{'Hit@k':>8}{'MRR':>8}{'avg ms':>9}")
        misses: dict[str, list[str]] = {}
        for mode in MODES:
            hits_at_k, reciprocal_ranks = 0, 0.0
            started = time.perf_counter()
            for case, emb in zip(cases, embeddings):
                rank = first_relevant_rank(search(conn, case["question"], emb, args.k, mode, documents), case["expected"])
                if rank:
                    hits_at_k += 1
                    reciprocal_ranks += 1 / rank
                else:
                    misses.setdefault(mode, []).append(case["question"])
            avg_ms = (time.perf_counter() - started) * 1000 / len(cases)
            print(f"{mode:<10}{hits_at_k / len(cases):>8.2f}{reciprocal_ranks / len(cases):>8.2f}{avg_ms:>9.1f}")

    if args.misses:
        for mode, questions in misses.items():
            print(f"\nMissed by {mode}:")
            for question in questions:
                print(f"  - {question}")


if __name__ == "__main__":
    main()
