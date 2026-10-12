"""Measure whether the final answers are right, not only whether search found the right passage.

For every question in the eval file the full pipeline runs (search + LLM answer), then three checks:

  Answer accuracy    An LLM judge compares the answer with the reference `answer` from the eval file.
  Citation accuracy  Deterministic: at least one passage the answer cites with [n] contains the
                     `expected` phrase, i.e. the answer points at the right part of the law.
  Abstention         Questions with "answer": null are not covered by the documents; the system
                     must say it could not find the answer instead of using general knowledge.

The judge is the same chat model unless --judge-model is given; a model grading its own answers
can be lenient, so failures are printed with the judge's reason for a human to check.

Usage: python -m scripts.evaluate_answers eval/questions.jsonl --document "Zakon o radu.pdf" [--mode vector] [--limit 5] [--out results.json]
"""
import argparse
import json
import re
from pathlib import Path

import openai

from app import db, llm, rag
from app.config import settings
from scripts.evaluate import comparable, document_ids

JUDGE_IN_SCOPE = """You grade answers from a question-answering system about Serbian law.

Question: {question}
Reference answer (correct): {reference}
System answer: {answer}

The system answer is CORRECT if it states the same key facts as the reference: numbers, durations,
percentages and conditions. Different wording, extra correct detail, or a different script
(Latin/Cyrillic) is fine. It is INCORRECT if a key fact is missing or different, or if it says
it could not find the answer.

Reply with JSON only: {{"correct": true or false, "reason": "one short sentence"}}"""

JUDGE_OUT_OF_SCOPE = """You grade a question-answering system that must only answer from the provided documents.
The question below is NOT covered by the documents, so the system should say it could not find
the answer, and must not answer from general knowledge.

Question: {question}
System answer: {answer}

Is the system answer a refusal (correct) or an attempt to answer (incorrect)?
Reply with JSON only: {{"correct": true or false, "reason": "one short sentence"}}"""


def parse_verdict(text: str) -> tuple[bool, str]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        verdict = json.loads(match.group(0)) if match else {}
        return bool(verdict["correct"]), str(verdict.get("reason", ""))
    except (json.JSONDecodeError, KeyError, TypeError):
        return False, f"Judge reply could not be parsed: {text!r:.120}"


def cited_numbers(answer: str) -> set[int]:
    """Passage numbers cited as [1], [1][3] or [1, 3]."""
    return {int(n) for group in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", answer) for n in re.findall(r"\d+", group)}


def cites_expected(answer: str, sources: list[dict], expected: str) -> bool:
    cited = cited_numbers(answer)
    needle = comparable(expected)
    return any(s["n"] in cited and needle in comparable(s["text"]) for s in sources)


def judge(case: dict, answer: str, model: str | None) -> tuple[bool, str]:
    if case.get("answer") is None:
        prompt = JUDGE_OUT_OF_SCOPE.format(question=case["question"], answer=answer)
    else:
        prompt = JUDGE_IN_SCOPE.format(question=case["question"], reference=case["answer"], answer=answer)
    reply, _ = llm.chat([{"role": "user", "content": prompt}], model=model)
    return parse_verdict(reply)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("eval_file")
    parser.add_argument("--mode", default="vector", choices=["vector", "keyword", "hybrid"])
    parser.add_argument("--k", type=int, default=settings.top_k)
    parser.add_argument("--limit", type=int, help="only the first N questions (quick check)")
    parser.add_argument("--judge-model", help="grade with a different chat model than the one answering")
    parser.add_argument("--out", type=Path, help="write per-question results as JSON")
    parser.add_argument("--document", action="append", help="only search this document (filename; repeatable)")
    args = parser.parse_args()

    cases = [json.loads(line) for line in Path(args.eval_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = [c for c in cases if "answer" in c][: args.limit]
    print(f"{len(cases)} questions, mode={args.mode}, k={args.k}, model={settings.chat_model}, "
          f"judge={args.judge_model or settings.chat_model}\n")

    results = []
    with db.connect() as conn:
        documents = document_ids(conn, args.document)
        for i, case in enumerate(cases, start=1):
            try:
                response = rag.answer(conn, case["question"], args.k, args.mode, documents)
                correct, reason = judge(case, response["answer"], args.judge_model)
            except openai.APIError as e:
                # Typically a free-tier quota. Keep what was graded so far instead of losing the run.
                print(f"\nStopped at question {i}: {str(e)[:200]}")
                break
            in_scope = case["answer"] is not None
            cited = cites_expected(response["answer"], response["sources"], case["expected"]) if case.get("expected") else None
            results.append({
                "question": case["question"], "in_scope": in_scope, "correct": correct, "reason": reason,
                "cites_right_passage": cited, "answer": response["answer"], "reference": case["answer"],
                "latency_ms": response["latency_ms"], "tokens": sum(response["usage"].values()),
            })
            mark = "ok " if correct else "BAD"
            print(f"[{i:>2}/{len(cases)}] {mark} {case['question']}", flush=True)

    if not results:
        raise SystemExit("No questions were graded.")
    if len(results) < len(cases):
        print(f"\nPartial run: {len(results)} of {len(cases)} questions graded.")
    in_scope = [r for r in results if r["in_scope"]]
    out_of_scope = [r for r in results if not r["in_scope"]]
    with_citation_check = [r for r in in_scope if r["cites_right_passage"] is not None]

    def rate(rows, key):
        return f"{sum(1 for r in rows if r[key])}/{len(rows)} ({sum(1 for r in rows if r[key]) / len(rows):.0%})" if rows else "-"

    print(f"\nAnswer accuracy     {rate(in_scope, 'correct')}")
    print(f"Citation accuracy   {rate(with_citation_check, 'cites_right_passage')}")
    print(f"Abstention          {rate(out_of_scope, 'correct')}")
    print(f"Avg latency         {sum(r['latency_ms'] for r in results) / len(results) / 1000:.1f} s per answer")
    print(f"Tokens (answers)    {sum(r['tokens'] for r in results)}")

    failures = [r for r in results if not r["correct"] or r["cites_right_passage"] is False]
    for r in failures:
        print(f"\n- {r['question']}")
        if not r["correct"]:
            print(f"  judge: {r['reason']}")
        if r["cites_right_passage"] is False:
            print("  citation: no cited passage contains the expected text")
        print(f"  answer: {r['answer'][:300]}")

    if args.out:
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nDetails written to {args.out}")


if __name__ == "__main__":
    main()
