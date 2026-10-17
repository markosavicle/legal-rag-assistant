# Evaluation report

100 cases · mode `vector` · k=5 · answer model `gemini-3.5-flash-lite` · judge `gemini-3.1-flash-lite`

## Retrieval (cases with an expected passage)

| Mode | Hit@k | Recall@k | MRR |
|---|---|---|---|
| vector | 1.00 | 1.00 | 0.91 |
| keyword | 0.79 | 0.79 | 0.62 |
| hybrid | 0.89 | 0.90 | 0.75 |

## Answers

| Check | Result |
|---|---|
| **Overall pass** (judge correct + right citation) | **98/100 (98%)** |
| Answer accuracy (judge), answerable | 85/87 (98%) |
| Abstention (judge), unanswerable | 13/13 (100%) |
| Cites the expected passage | 87/87 (100%) |
| Rule-based checks pass | 93/94 (99%) |
| Rules agree with judge | 93/94 (99%) |
| Grounded (judge) | 100/100 (100%) |
| Answers with a number found in no passage | 0 |
| Avg latency per answer | 10.9 s |

## By category

| Category | Cases | Retrieval hit | Pass |
|---|---|---|---|
| factual | 40 | 40/40 (100%) | 40/40 (100%) |
| cyrillic | 4 | 4/4 (100%) | 4/4 (100%) |
| article | 6 | 6/6 (100%) | 5/6 (83%) |
| contract | 12 | 12/12 (100%) | 12/12 (100%) |
| comparison | 5 | 5/5 (100%) | 5/5 (100%) |
| conflict | 7 | 7/7 (100%) | 7/7 (100%) |
| ambiguous | 11 | 11/11 (100%) | 11/11 (100%) |
| out_of_scope | 10 | - | 10/10 (100%) |
| false_premise | 5 | 2/2 (100%) | 4/5 (80%) |

## Failures by root cause

| Category | Count |
|---|---|
| missed_retrieval | 0 |
| hallucination | 0 |
| wrong_citation | 0 |
| false_abstention | 1 |
| incomplete_answer | 1 |

## Failed cases

- **art-03** `incomplete_answer`: Šta je uređeno članom 36?
  - judge: The answer is incomplete as it omits the duration of the probationary period and the notice period, which are key facts present in the reference and the retrieved passage.
  - answer: Članom 36. ugovorom o radu može da se ugovori probni rad za obavljanje jednog ili više povezanih, odnosno srodnih poslova utvrđenih ugovorom o radu [1].
- **fp-03** `false_abstention`: Koji član Zakona o radu daje pravo na 30 dana godišnjeg odmora svim zaposlenima?
  - judge: The system failed to identify that the provided documents contain the information necessary to refute the premise of the question.
  - answer: Ne mogao sam pronaći odgovor u dokumentima [1][2][3][4][5].

## Rules vs judge disagreements (for human review)

- **art-03** rules=pass (no abstention phrase), judge=incorrect: The answer is incomplete as it omits the duration of the probationary period and the notice period, which are key facts present in the reference and the retrieved passage.
