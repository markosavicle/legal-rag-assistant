"""Measure retrieval quality for each search mode.

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


def first_relevant_rank(hits, expected: str) -> int | None:
    needle = expected.lower()
    for rank, hit in enumerate(hits, start=1):
        if needle in hit.content.lower():
            return rank
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("eval_file")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    cases = [json.loads(line) for line in Path(args.eval_file).read_text(encoding="utf-8").splitlines() if line.strip()]

    with db.connect() as conn:
        embeddings = [embed_query(conn, c["question"]) for c in cases]
        print(f"{len(cases)} questions, k={args.k}\n")
        print(f"{'mode':<10}{'Hit@k':>8}{'MRR':>8}{'avg ms':>9}")
        for mode in MODES:
            hits_at_k, reciprocal_ranks = 0, 0.0
            started = time.perf_counter()
            for case, emb in zip(cases, embeddings):
                rank = first_relevant_rank(search(conn, case["question"], emb, args.k, mode), case["expected"])
                if rank:
                    hits_at_k += 1
                    reciprocal_ranks += 1 / rank
            avg_ms = (time.perf_counter() - started) * 1000 / len(cases)
            print(f"{mode:<10}{hits_at_k / len(cases):>8.2f}{reciprocal_ranks / len(cases):>8.2f}{avg_ms:>9.1f}")


if __name__ == "__main__":
    main()
