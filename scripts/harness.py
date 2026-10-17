"""Evaluation harness: retrieval and answer quality on eval/testset.jsonl, with failure categories.

Each line of the test set is one case:

  id, category        e.g. "cf-01", "conflict"
  question
  documents           filenames the question is asked about (as if ticked in the UI); omitted = all
  expected            phrases the right passage(s) contain; "match": "all" (default) or "any"
  answer              reference answer, may include grading notes; null = the documents do not
                      answer it and the system must say so
  must_include        rule-based checks on the answer: every item must appear ("a|b" = either)
  must_not_include    rule-based checks: none of these may appear

For every case the harness checks

  retrieval   did search return the expected passage(s)? Hit, recall and MRR, for every search mode
  rules       deterministic: required / forbidden terms, abstention phrasing, citations that point
              at a passage containing the expected text, numbers that appear in no retrieved passage
  judge       an LLM compares the answer with the reference (correct?) and with the retrieved
              passages (grounded?)

A case passes when the judge says correct and, if it has an expected passage, the answer cites it.
Failed cases get one root-cause category: missed_retrieval, hallucination, wrong_citation,
false_abstention or incomplete_answer.

Usage:
  python -m scripts.harness eval/testset.jsonl --check          # validate the test set, no LLM calls
  python -m scripts.harness eval/testset.jsonl --retrieval-only
  python -m scripts.harness eval/testset.jsonl --judge-model gemini-3.1-flash-lite --out eval
  python -m scripts.harness eval/testset.jsonl --judge-model ... --out eval --resume   # after a quota stop
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import openai

from app import db, llm, rag
from app.config import settings
from app.search import MODES, search
from scripts.evaluate import comparable
from scripts.evaluate_answers import cited_numbers

CATEGORIES = ("factual", "cyrillic", "article", "contract", "comparison", "conflict", "ambiguous",
              "out_of_scope", "false_premise")
FAILURES = ("missed_retrieval", "hallucination", "wrong_citation", "false_abstention", "incomplete_answer")
FIELDS = {"id", "category", "question", "documents", "expected", "match", "answer", "must_include", "must_not_include"}

# ---------------------------------------------------------------------------------------------
# Test set
# ---------------------------------------------------------------------------------------------


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_cases(cases: list[dict]) -> list[str]:
    """Structural problems in the test set (no database needed)."""
    errors = []
    ids = Counter(c.get("id") for c in cases)
    errors += [f"duplicate id {id_}" for id_, n in ids.items() if n > 1]
    for c in cases:
        where = c.get("id", c.get("question", "?"))
        if unknown := set(c) - FIELDS:
            errors.append(f"{where}: unknown fields {sorted(unknown)}")
        for field in ("id", "category", "question"):
            if not c.get(field):
                errors.append(f"{where}: missing {field}")
        if "answer" not in c:
            errors.append(f"{where}: missing answer (use null for questions the documents do not answer)")
        if c.get("category") not in CATEGORIES:
            errors.append(f"{where}: unknown category {c.get('category')!r}")
        if c.get("match", "all") not in ("all", "any"):
            errors.append(f"{where}: match must be 'all' or 'any'")
        if c.get("answer") is None and (c.get("expected") or c.get("must_include")):
            errors.append(f"{where}: a question without an answer cannot have expected passages or must_include")
        if c.get("answer") is not None and not c.get("expected"):
            errors.append(f"{where}: an answerable question needs an expected passage")
        for field in ("documents", "expected", "must_include", "must_not_include"):
            if field in c and not (isinstance(c[field], list) and all(isinstance(x, str) and x for x in c[field])):
                errors.append(f"{where}: {field} must be a list of non-empty strings")
    return errors


def scope_ids(case: dict, ids_by_name: dict[str, int]) -> list[int] | None:
    names = case.get("documents")
    return [ids_by_name[n] for n in names] if names else None


def check_against_index(conn, cases: list[dict], ids_by_name: dict[str, int]) -> list[str]:
    """Every scoped document is indexed and every expected phrase exists in one of them,
    so a retrieval miss is a search problem, never a typo in the test set."""
    errors = []
    for c in cases:
        missing = [n for n in c.get("documents", []) if n not in ids_by_name]
        if missing:
            errors.append(f"{c['id']}: documents not indexed: {missing}")
            continue
        scope = scope_ids(c, ids_by_name) or list(ids_by_name.values())
        rows = conn.execute("SELECT content FROM chunks WHERE document_id = ANY(%s)", (scope,)).fetchall()
        texts = [comparable(content) for (content,) in rows]
        for phrase in c.get("expected", []):
            if not any(comparable(phrase) in t for t in texts):
                errors.append(f"{c['id']}: expected phrase not found in its documents: {phrase!r}")
    return errors


# ---------------------------------------------------------------------------------------------
# Rule-based checks
# ---------------------------------------------------------------------------------------------

_FOLD = str.maketrans({"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "dj"})


def fold(text: str) -> str:
    """Latin script, lower case, no diacritics, single spaces: what rules compare on."""
    return comparable(text).translate(_FOLD)


def contains_term(text: str, term: str) -> bool:
    """`term` may list alternatives as "a|b". Terms match at a word start ("prosečn" matches
    "prosečne"), and numbers match whole ("6" does not match "26" or "60")."""
    folded = fold(text)
    for alt in term.split("|"):
        alt = fold(alt)
        tail = r"(?!\d)" if alt[-1:].isdigit() else ""
        if re.search(rf"(?<!\w){re.escape(alt)}{tail}", folded):
            return True
    return False


def strip_citations(answer: str) -> str:
    return re.sub(r"\[\d+(?:\s*,\s*\d+)*\]", " ", answer)


# Number words, so "pet radnih dana" in a passage supports "5 radnih dana" in an answer.
_NUMBER_WORDS = {
    "jedan": 1, "jednog": 1, "jedne": 1, "jedna": 1, "dva": 2, "dve": 2, "tri": 3, "cetiri": 4,
    "pet": 5, "sest": 6, "sedam": 7, "osam": 8, "devet": 9, "deset": 10, "jedanaest": 11, "dvanaest": 12,
    "petnaest": 15, "dvadeset": 20, "trideset": 30, "sezdeset": 60,
}


def numbers_in(text: str, with_words: bool = False) -> set[str]:
    folded = fold(text)
    found = {n.lstrip("0") or "0" for n in re.findall(r"\d+", folded)}
    if with_words:
        found |= {str(_NUMBER_WORDS[w]) for w in re.findall(r"\w+", folded) if w in _NUMBER_WORDS}
    return found


def unsupported_numbers(answer: str, question: str, sources: list[dict]) -> list[str]:
    """Numbers in the answer that appear in no retrieved passage and not in the question:
    a cheap hallucination signal (an invented duration, amount or article)."""
    supported = numbers_in(question, with_words=True)
    for s in sources:
        # The passage label ("Zakon o radu.pdf, page 21") is shown to the model too.
        supported |= numbers_in(s["text"], with_words=True) | numbers_in(s["source"])
    return sorted(numbers_in(strip_citations(answer)) - supported, key=int)


# Phrases the system uses to say the documents do not answer the question (Serbian and English).
_ABSTAIN = re.compile(
    r"(nisam|nismo|ne mogu|ne mogao|ne mogla|ne mozemo|nije moguce)\b.{0,40}\b(pronac|pronas|nac|nas|naci|da odgovor|pronadj)"
    r"|(nije|nisu)\s+(pronadjen|naveden|navedeno|navedena|pomenut|sadrzan)"
    r"|(dokument|kontekst|odlom|pasus|tekst|ugovor|zakon|aneks)\w*\b.{0,60}\b(ne sadrz|ne navod|ne pominj|ne spominj|ne propisuj|ne uredjuj|ne regulis|ne daje informac|nema (podat|informac|odredb))"
    r"|nema (podataka|informacija|odredb)"
    r"|could not find|couldn't find|cannot find|can't find|not (found|mentioned|covered|specified)|does not (contain|mention|specify)|no information"
)


def abstained(answer: str) -> bool:
    return bool(_ABSTAIN.search(fold(answer)))


def rule_checks(case: dict, answer: str, sources: list[dict]) -> dict:
    missing = [t for t in case.get("must_include", []) if not contains_term(answer, t)]
    forbidden = [t for t in case.get("must_not_include", []) if contains_term(answer, t)]
    declined = abstained(answer)
    if case["answer"] is None:
        passed = declined and not forbidden
    else:
        passed = not missing and not forbidden
    return {
        "passed": passed, "missing": missing, "forbidden": forbidden, "abstained": declined,
        "unsupported_numbers": unsupported_numbers(answer, case["question"], sources),
    }


def citation_checks(case: dict, answer: str, sources: list[dict]) -> dict:
    """Which passages the answer cites, whether they exist, and whether they hold the expected text."""
    cited = cited_numbers(answer)
    available = {s["n"] for s in sources}
    invalid = sorted(cited - available)
    expected = case.get("expected", [])
    cited_texts = [comparable(s["text"]) for s in sources if s["n"] in cited]
    found = [any(comparable(p) in t for t in cited_texts) for p in expected]
    if not expected:
        right = None
    elif case.get("match", "all") == "any":
        right = any(found) and not invalid
    else:
        right = all(found) and not invalid
    return {"cited": sorted(cited), "invalid": invalid, "uncited": not cited, "cites_expected": right}


# ---------------------------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------------------------


def retrieval_scores(case: dict, hits) -> dict:
    """Rank of each expected phrase among the hits, and whether retrieval succeeded."""
    contents = [comparable(h.content) for h in hits]
    ranks = []
    for phrase in case["expected"]:
        needle = comparable(phrase)
        ranks.append(next((i for i, text in enumerate(contents, start=1) if needle in text), None))
    found = [r for r in ranks if r]
    hit = bool(found) if case.get("match", "all") == "any" else len(found) == len(ranks)
    return {
        "hit": hit,
        "recall": len(found) / len(ranks) if case.get("match", "all") == "all" else float(bool(found)),
        "rr": 1 / min(found) if found else 0.0,
        "ranks": ranks,
    }


# ---------------------------------------------------------------------------------------------
# LLM judge
# ---------------------------------------------------------------------------------------------

JUDGE_ANSWER = """You grade answers from a question-answering system over Serbian legal documents (a labour law and employment contracts).

Question: {question}
Reference answer, possibly with grading notes: {reference}

Passages the system retrieved, numbered as the system saw them:
{passages}

System answer: {answer}

Decide two things.
correct: the answer states the same key facts as the reference (numbers, durations, percentages,
conditions, and which person or document a fact belongs to) and follows any grading notes in the
reference. Different wording, extra correct detail, or another script (Latin/Cyrillic) is fine.
A missing or different key fact, or saying the answer could not be found, is incorrect.
grounded: every factual claim in the answer is supported by the passages above. A claim that is not
in the passages (general knowledge, an invented number) makes it ungrounded, even if it is true.

Reply with JSON only: {{"correct": true or false, "grounded": true or false, "reason": "one short sentence"}}"""

JUDGE_ABSTAIN = """You grade a question-answering system that must answer only from the provided documents.
The documents do NOT answer the question below: it is out of scope, or it assumes something the
documents do not say. The system should say it could not find the answer or that the documents do not
cover it. It must not answer from general knowledge or invent facts. Mentioning what the documents do
say on a related point is fine.

Question: {question}

Passages the system retrieved:
{passages}

System answer: {answer}

correct: the answer declines, or says the documents do not contain this, without inventing an answer.
grounded: everything the answer does state is supported by the passages.

Reply with JSON only: {{"correct": true or false, "grounded": true or false, "reason": "one short sentence"}}"""

PASSAGE_CHARS = 1500


def format_passages(sources: list[dict]) -> str:
    if not sources:
        return "(none)"
    return "\n\n".join(f"[{s['n']}] ({s['source']})\n{s['text'][:PASSAGE_CHARS]}" for s in sources)


def parse_judgement(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        verdict = json.loads(match.group(0)) if match else {}
        return {"correct": bool(verdict["correct"]), "grounded": bool(verdict.get("grounded", True)),
                "reason": str(verdict.get("reason", ""))}
    except (json.JSONDecodeError, KeyError, TypeError):
        return {"correct": False, "grounded": True, "reason": f"Judge reply could not be parsed: {text!r:.120}"}


def judge(case: dict, answer: str, sources: list[dict], model: str | None) -> dict:
    template = JUDGE_ABSTAIN if case["answer"] is None else JUDGE_ANSWER
    prompt = template.format(question=case["question"], reference=case["answer"],
                             passages=format_passages(sources), answer=answer)
    reply, _ = llm.chat([{"role": "user", "content": prompt}], model=model)
    return parse_judgement(reply)


# ---------------------------------------------------------------------------------------------
# Verdict and failure category
# ---------------------------------------------------------------------------------------------


def classify(result: dict) -> str | None:
    """One root cause per failed case, checked in pipeline order."""
    if result["passed"]:
        return None
    if result["answer_expected"] is False:
        return "hallucination"  # answered a question the documents do not answer
    if result["retrieval"] and not result["retrieval"]["hit"]:
        return "missed_retrieval"
    if result["judge"]["correct"]:
        return "wrong_citation"
    if result["rules"]["abstained"]:
        return "false_abstention"
    if not result["judge"]["grounded"] or result["rules"]["unsupported_numbers"]:
        return "hallucination"
    return "incomplete_answer"


def regrade(result: dict, case: dict) -> dict:
    """Re-apply the rule checks to a saved result after the rules changed, without LLM calls.
    Passages are not saved, so numbers-in-no-passage only drops numbers from the passage labels."""
    answer = result["answer"]
    rules = {**result["rules"],
             "missing": [t for t in case.get("must_include", []) if not contains_term(answer, t)],
             "forbidden": [t for t in case.get("must_not_include", []) if contains_term(answer, t)],
             "abstained": abstained(answer)}
    rules["passed"] = (rules["abstained"] if case["answer"] is None else not rules["missing"]) and not rules["forbidden"]
    labels = set().union(*(numbers_in(s["source"]) for s in result["sources"]))
    rules["unsupported_numbers"] = [n for n in rules["unsupported_numbers"] if n not in labels]
    updated = {**result, "rules": rules,
               "has_rules": case["answer"] is None or bool(case.get("must_include") or case.get("must_not_include"))}
    updated["failure"] = classify(updated)
    return updated


def grade(case: dict, response: dict, retrieval: dict | None, verdict: dict) -> dict:
    answer, sources = response["answer"], response["sources"]
    rules = rule_checks(case, answer, sources)
    citations = citation_checks(case, answer, sources)
    passed = verdict["correct"] and citations["cites_expected"] is not False
    result = {
        "id": case["id"], "category": case["category"], "question": case["question"],
        "documents": case.get("documents"), "answer_expected": case["answer"] is not None,
        "has_rules": case["answer"] is None or bool(case.get("must_include") or case.get("must_not_include")),
        "passed": passed, "judge": verdict, "rules": rules, "citations": citations, "retrieval": retrieval,
        "answer": answer, "reference": case["answer"],
        "sources": [{"n": s["n"], "source": s["source"], "chunk_id": s["chunk_id"]} for s in sources],
        "latency_ms": response["latency_ms"], "tokens": sum(response["usage"].values()),
    }
    result["failure"] = classify(result)
    return result


# ---------------------------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------------------------


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "-"


def retrieval_table(retrieval_by_mode: dict[str, list[dict]]) -> list[str]:
    lines = ["| Mode | Hit@k | Recall@k | MRR |", "|---|---|---|---|"]
    for mode, rows in retrieval_by_mode.items():
        n = len(rows)
        lines.append(f"| {mode} | {sum(r['hit'] for r in rows) / n:.2f} | {sum(r['recall'] for r in rows) / n:.2f} "
                     f"| {sum(r['rr'] for r in rows) / n:.2f} |")
    return lines


def build_report(results: list[dict], retrieval_by_mode: dict[str, list[dict]], meta: dict) -> str:
    lines = [f"# Evaluation report", "",
             f"{len(results)} cases · mode `{meta['mode']}` · k={meta['k']} · answer model `{meta['model']}` · "
             f"judge `{meta['judge']}`", ""]

    lines += ["## Retrieval (cases with an expected passage)", ""] + retrieval_table(retrieval_by_mode) + [""]

    answerable = [r for r in results if r["answer_expected"]]
    unanswerable = [r for r in results if not r["answer_expected"]]
    cite_rows = [r for r in answerable if r["citations"]["cites_expected"] is not None]
    rule_rows = [r for r in results if r["has_rules"]]
    agree = [r for r in rule_rows if r["rules"]["passed"] == r["judge"]["correct"]]
    ungrounded = [r for r in results if not r["judge"]["grounded"]]
    with_unsupported = [r for r in results if r["rules"]["unsupported_numbers"]]
    lines += ["## Answers", "", "| Check | Result |", "|---|---|",
              f"| **Overall pass** (judge correct + right citation) | **{pct(sum(r['passed'] for r in results), len(results))}** |",
              f"| Answer accuracy (judge), answerable | {pct(sum(r['judge']['correct'] for r in answerable), len(answerable))} |",
              f"| Abstention (judge), unanswerable | {pct(sum(r['judge']['correct'] for r in unanswerable), len(unanswerable))} |",
              f"| Cites the expected passage | {pct(sum(bool(r['citations']['cites_expected']) for r in cite_rows), len(cite_rows))} |",
              f"| Rule-based checks pass | {pct(sum(r['rules']['passed'] for r in rule_rows), len(rule_rows))} |",
              f"| Rules agree with judge | {pct(len(agree), len(rule_rows))} |",
              f"| Grounded (judge) | {pct(len(results) - len(ungrounded), len(results))} |",
              f"| Answers with a number found in no passage | {len(with_unsupported)} |",
              f"| Avg latency per answer | {sum(r['latency_ms'] for r in results) / len(results) / 1000:.1f} s |",
              ""]

    lines += ["## By category", "", "| Category | Cases | Retrieval hit | Pass |", "|---|---|---|---|"]
    by_cat = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)
    for cat in CATEGORIES:
        rows = by_cat.get(cat, [])
        if not rows:
            continue
        with_ret = [r for r in rows if r["retrieval"]]
        ret = pct(sum(r["retrieval"]["hit"] for r in with_ret), len(with_ret)) if with_ret else "-"
        lines.append(f"| {cat} | {len(rows)} | {ret} | {pct(sum(r['passed'] for r in rows), len(rows))} |")
    lines.append("")

    failures = Counter(r["failure"] for r in results if r["failure"])
    lines += ["## Failures by root cause", "", "| Category | Count |", "|---|---|"]
    lines += [f"| {f} | {failures.get(f, 0)} |" for f in FAILURES] + [""]

    lines += ["## Failed cases", ""]
    for r in results:
        if not r["failure"]:
            continue
        lines.append(f"- **{r['id']}** `{r['failure']}`: {r['question']}")
        lines.append(f"  - judge: {r['judge']['reason']}")
        if r["retrieval"] and not r["retrieval"]["hit"]:
            lines.append(f"  - expected passage ranks: {r['retrieval']['ranks']}")
        if r["rules"]["unsupported_numbers"]:
            lines.append(f"  - numbers in no passage: {', '.join(r['rules']['unsupported_numbers'])}")
        if r["citations"]["cites_expected"] is False:
            lines.append(f"  - cited {r['citations']['cited'] or 'nothing'}, expected passage not among them")
        lines.append(f"  - answer: {' '.join(r['answer'].split())[:300]}")
    lines.append("")

    disagreements = [r for r in rule_rows if r["rules"]["passed"] != r["judge"]["correct"]]
    if disagreements:
        lines += ["## Rules vs judge disagreements (for human review)", ""]
        for r in disagreements:
            detail = (f"missing {r['rules']['missing']}" if r["rules"]["missing"] else
                      f"forbidden {r['rules']['forbidden']}" if r["rules"]["forbidden"] else
                      "abstained" if r["rules"]["abstained"] else "no abstention phrase")
            lines.append(f"- **{r['id']}** rules={'pass' if r['rules']['passed'] else 'fail'} ({detail}), "
                         f"judge={'correct' if r['judge']['correct'] else 'incorrect'}: {r['judge']['reason']}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("eval_file", type=Path)
    parser.add_argument("--check", action="store_true", help="validate the test set against the index and stop")
    parser.add_argument("--retrieval-only", action="store_true", help="score retrieval for every mode, no LLM calls")
    parser.add_argument("--mode", default="vector", choices=MODES, help="search mode for answers")
    parser.add_argument("--k", type=int, default=settings.top_k)
    parser.add_argument("--only", nargs="+", help="only these case ids or categories")
    parser.add_argument("--judge-model", help="grade with a different chat model than the one answering")
    parser.add_argument("--out", type=Path, help="folder for results.json and report.md")
    parser.add_argument("--resume", action="store_true", help="skip cases already in <out>/results.json")
    parser.add_argument("--regrade", action="store_true",
                        help="re-score <out>/results.json with the current rule checks (no chat calls), rewrite the report")
    args = parser.parse_args()
    if (args.resume or args.regrade) and not args.out:
        sys.exit("--resume and --regrade need --out")

    cases = load_cases(args.eval_file)
    if errors := validate_cases(cases):
        sys.exit("Test set errors:\n  " + "\n  ".join(errors))
    if args.only:
        cases = [c for c in cases if c["id"] in args.only or c["category"] in args.only]

    with db.connect() as conn:
        ids_by_name = {name: id_ for id_, name in conn.execute("SELECT id, filename FROM documents")}
        if errors := check_against_index(conn, cases, ids_by_name):
            sys.exit("Test set does not match the index:\n  " + "\n  ".join(errors))
        print(f"Test set OK: {len(cases)} cases, {dict(Counter(c['category'] for c in cases))}")
        if args.check:
            return

        # Retrieval for every mode (cheap: one cached embedding per question, no chat calls).
        embeddings = {c["id"]: llm.embed_query(conn, c["question"]) for c in cases}
        retrieval_by_mode: dict[str, list[dict]] = {}
        retrieval_default: dict[str, dict] = {}
        for mode in MODES:
            rows = []
            for c in (c for c in cases if c.get("expected")):
                hits = search(conn, c["question"], embeddings[c["id"]], args.k, mode, scope_ids(c, ids_by_name))
                scores = retrieval_scores(c, hits)
                rows.append(scores)
                if mode == args.mode:
                    retrieval_default[c["id"]] = scores
            retrieval_by_mode[mode] = rows
        print("\n".join(retrieval_table(retrieval_by_mode)))
        if args.retrieval_only:
            for c in cases:
                if c["id"] in retrieval_default and not retrieval_default[c["id"]]["hit"]:
                    print(f"  miss ({args.mode}) {c['id']}: {c['question']}  ranks={retrieval_default[c['id']]['ranks']}")
            return

        results_path = args.out / "results.json" if args.out else None
        done = {}
        if args.resume and results_path and results_path.exists():
            done = {r["id"]: r for r in json.loads(results_path.read_text(encoding="utf-8"))}
        results = []
        if args.regrade:
            by_id = {c["id"]: c for c in cases}
            saved = json.loads(results_path.read_text(encoding="utf-8"))
            results = [regrade(r, by_id[r["id"]]) for r in saved if r["id"] in by_id]
            cases = [by_id[r["id"]] for r in results]
        else:
            print(f"\nAnswering with {settings.chat_model}, judging with {args.judge_model or settings.chat_model}")
        for i, c in enumerate([] if args.regrade else cases, start=1):
            if c["id"] in done:
                results.append(done[c["id"]])
                continue
            try:
                response = rag.answer(conn, c["question"], args.k, args.mode, scope_ids(c, ids_by_name))
                verdict = judge(c, response["answer"], response["sources"], args.judge_model)
            except openai.APIError as e:
                # Typically a free-tier quota: keep what was graded, and --resume later.
                print(f"\nStopped at {c['id']}: {str(e)[:200]}")
                break
            result = grade(c, response, retrieval_default.get(c["id"]), verdict)
            results.append(result)
            print(f"[{i:>3}/{len(cases)}] {'ok ' if result['passed'] else 'BAD'} {c['id']:<7} "
                  f"{result['failure'] or ''}", flush=True)

    if not results:
        sys.exit("No cases were graded.")
    meta = {"mode": args.mode, "k": args.k, "model": settings.chat_model, "judge": args.judge_model or settings.chat_model}
    report = build_report(results, retrieval_by_mode, meta)
    if len(results) < len(cases):
        report = f"> Partial run: {len(results)} of {len(cases)} cases graded.\n\n" + report
    print("\n" + report)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        (args.out / "report.md").write_text(report, encoding="utf-8")
        print(f"Written {results_path} and {args.out / 'report.md'}")


if __name__ == "__main__":
    main()
