# Evaluation report

100 cases · mode `vector` · k=5 · answer model `gemini-3.5-flash-lite` · judge `gemini-3.1-flash-lite`

## Retrieval (cases with an expected passage)

| Mode | Hit@k | Recall@k | MRR |
|---|---|---|---|
| vector | 1.00 | 1.00 | 0.90 |
| keyword | 0.78 | 0.78 | 0.61 |
| hybrid | 0.89 | 0.90 | 0.75 |

## Answers

| Check | Result |
|---|---|
| **Overall pass** (judge correct + right citation) | **91/100 (91%)** |
| Answer accuracy (judge), answerable | 80/87 (92%) |
| Abstention (judge), unanswerable | 12/13 (92%) |
| Cites the expected passage | 84/87 (97%) |
| Rule-based checks pass | 89/94 (95%) |
| Rules agree with judge | 89/94 (95%) |
| Grounded (judge) | 100/100 (100%) |
| Answers with a number found in no passage | 0 |
| Avg latency per answer | 13.0 s |

## By category

| Category | Cases | Retrieval hit | Pass |
|---|---|---|---|
| factual | 42 | 42/42 (100%) | 41/42 (98%) |
| cyrillic | 4 | 4/4 (100%) | 4/4 (100%) |
| article | 4 | 4/4 (100%) | 3/4 (75%) |
| contract | 12 | 12/12 (100%) | 12/12 (100%) |
| comparison | 5 | 5/5 (100%) | 5/5 (100%) |
| conflict | 7 | 7/7 (100%) | 5/7 (71%) |
| ambiguous | 11 | 11/11 (100%) | 8/11 (73%) |
| out_of_scope | 10 | - | 9/10 (90%) |
| false_premise | 5 | 2/2 (100%) | 4/5 (80%) |

## Failures by root cause

| Category | Count |
|---|---|
| missed_retrieval | 0 |
| hallucination | 1 |
| wrong_citation | 1 |
| false_abstention | 3 |
| incomplete_answer | 4 |

## Failed cases

- **law-38** `wrong_citation`: U kom roku zaposleni mora da se vrati na rad posle isteka mirovanja radnog odnosa?
  - judge: The answer correctly identifies the 15-day deadline and provides the specific legal context supported by the provided passages.
  - cited [1], expected passage not among them
  - answer: Zaposleni kome miruju prava i obaveze ima pravo da se vrati na rad kod poslodavca u roku od 15 dana od dana odsluženja, odnosno dosluženja vojnog roka, prestanka rada u inostranstvu, odnosno kod drugog poslodavca, prestanka funkcije, povratka sa izdržavanja kazne zatvora, odnosno mere bezbednosti, v
- **art-03** `incomplete_answer`: Šta je uređeno članom 36?
  - judge: The answer is incomplete as it omits the duration of the probationary period and the notice period, which are key facts present in the reference answer.
  - answer: Članom 36 je uređen probni rad koji može da se ugovori ugovorom o radu za obavljanje jednog ili više povezanih, odnosno srodnih poslova utvrđenih ugovorom o radu [2].
- **cf-03** `incomplete_answer`: Koliko dana godišnjeg odmora ima Ana Jović?
  - judge: The answer fails to identify the 18 days as the currently valid duration, contradicting the grading note which specifies that 22 days is incorrect.
  - answer: Ana Jović ima pravo na godišnji odmor u trajanju od 22 radna dana u kalendarskoj godini, prema ugovoru o radu [1], odnosno 18 radnih dana prema aneksu ugovora [2].
- **cf-06** `false_abstention`: Ugovor Ane Jović kaže da se zarada isplaćuje do 10. u mesecu, a zakon do kraja meseca. Koji rok važi za nju?
  - judge: The system failed to answer the question despite the necessary information being present in passages [2] and [3].
  - cited nothing, expected passage not among them
  - answer: I could not find it in the documents.
- **amb-05** `false_abstention`: Kolika je zarada?
  - judge: The system failed to extract the information that was clearly present in the provided passages.
  - cited nothing, expected passage not among them
  - answer: I could not find it in the documents.
- **amb-08** `incomplete_answer`: Šta mi pripada ako radim noću?
  - judge: The answer is grounded but incomplete because it fails to define night work (22:00 to 06:00) as specified in the reference answer and passage [1].
  - answer: Zaposleni ima pravo na uvećanu zaradu za rad noću u visini utvrđenoj opštim aktom i ugovorom o radu, a najmanje 26% od osnovice, ako takav rad nije vrednovan pri utvrđivanju osnovne zarade [3].
- **amb-09** `incomplete_answer`: Koliko traje probni rad?
  - judge: The answer is incomplete because it fails to mention the specific durations for the individual employees as required by the reference answer.
  - answer: Probni rad može da traje najduže šest meseci [3].
- **oos-10** `hallucination`: Koja je adresa stanovanja Nikole Ilića?
  - judge: Sistem je pogrešno identifikovao grad prebivališta kao adresu stanovanja, iako dokumenti ne sadrže konkretnu adresu.
  - answer: Adresa stanovanja Nikole Ilića je u Beogradu [1].
- **fp-03** `false_abstention`: Koji član Zakona o radu daje pravo na 30 dana godišnjeg odmora svim zaposlenima?
  - judge: The system failed to answer the question despite the information being present in passage [1], which explicitly states the minimum is 20 days.
  - answer: Could not find it in the documents [1][2][3][4][5].

## Rules vs judge disagreements (for human review)

- **art-01** rules=fail (missing ['22']), judge=correct: The system answer accurately summarizes the content of Article 62 as provided in the retrieved passage.
- **art-03** rules=pass (no abstention phrase), judge=incorrect: The answer is incomplete as it omits the duration of the probationary period and the notice period, which are key facts present in the reference answer.
- **cmp-03** rules=fail (missing ['ana']), judge=correct: The answer correctly identifies the contract types for both individuals based on the provided passages.
- **cf-03** rules=pass (no abstention phrase), judge=incorrect: The answer fails to identify the 18 days as the currently valid duration, contradicting the grading note which specifies that 22 days is incorrect.
- **amb-08** rules=pass (no abstention phrase), judge=incorrect: The answer is grounded but incomplete because it fails to define night work (22:00 to 06:00) as specified in the reference answer and passage [1].
