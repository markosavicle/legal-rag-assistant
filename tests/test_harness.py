from app.search import Hit
from scripts.harness import (
    abstained, citation_checks, classify, contains_term, parse_judgement, retrieval_scores, rule_checks,
    unsupported_numbers, validate_cases,
)

SOURCES = [
    {"n": 1, "source": "zakon.pdf", "chunk_id": 1, "text": "Član 69.\nZaposleni ima pravo na godišnji odmor od najmanje 20 radnih dana."},
    {"n": 2, "source": "zakon.pdf", "chunk_id": 2, "text": "Član 36.\nProbni rad može da traje najduže šest meseci."},
]
CASE = {"id": "t-1", "category": "factual", "question": "Koliko traje godišnji odmor?",
        "expected": ["najmanje 20 radnih dana"], "answer": "Najmanje 20 radnih dana.", "must_include": ["20"]}


def hit(chunk_id: int, content: str) -> Hit:
    return Hit(chunk_id=chunk_id, filename="zakon.pdf", page=1, chunk_index=chunk_id, content=content, score=0.0)


def test_terms_match_word_starts_alternatives_and_diacritics():
    assert contains_term("Dve prosečne zarade", "prosečn")
    assert contains_term("dve prosecne zarade", "prosečn")
    assert contains_term("Najduže 6 meseci", "šest|6")
    assert contains_term("Најмање 20 радних дана", "20")


def test_numbers_match_whole():
    assert not contains_term("najmanje 26% od osnovice", "6")
    assert not contains_term("60 dana", "6")
    assert contains_term("od 22 do 6,00 časova", "6")


def test_unsupported_numbers_flags_invented_values():
    assert unsupported_numbers("Najmanje 25 radnih dana [1].", "Koliko?", SOURCES) == ["25"]


def test_unsupported_numbers_accepts_number_words_and_ignores_citations():
    assert unsupported_numbers("Najduže 6 meseci [2].", "Koliko?", SOURCES) == []
    assert unsupported_numbers("Najmanje 20 radnih dana [1][2].", "Koliko?", SOURCES) == []


def test_abstention_phrases():
    assert abstained("Nisam mogao da pronađem odgovor u dokumentima.")
    assert abstained("Dokumenti ne sadrže informacije o tome.")
    assert abstained("I could not find this in the documents.")
    assert abstained("Ugovor ne navodi razlog otkaza.")
    assert not abstained("Rad od kuće nije predviđen [1].")
    assert not abstained("Najmanje 20 radnih dana [1].")


def test_rule_checks_for_an_answer():
    assert rule_checks(CASE, "Najmanje 20 radnih dana [1].", SOURCES)["passed"]
    result = rule_checks(CASE, "Najmanje 22 radna dana [1].", SOURCES)
    assert not result["passed"] and result["missing"] == ["20"] and result["unsupported_numbers"] == ["22"]


def test_rule_checks_forbidden_terms():
    case = {**CASE, "must_not_include": ["šest"]}
    assert rule_checks(case, "20 radnih dana, probni rad šest meseci [1].", SOURCES)["forbidden"] == ["šest"]


def test_rule_checks_for_an_unanswerable_question():
    case = {"id": "t-2", "category": "out_of_scope", "question": "Kolika je stopa PDV-a?", "answer": None}
    assert rule_checks(case, "Nisam pronašao odgovor u dokumentima.", SOURCES)["passed"]
    assert not rule_checks(case, "Stopa PDV-a je 20%.", SOURCES)["passed"]


def test_citation_checks():
    assert citation_checks(CASE, "Najmanje 20 radnih dana [1].", SOURCES)["cites_expected"]
    wrong = citation_checks(CASE, "Najmanje 20 radnih dana [2].", SOURCES)
    assert wrong["cites_expected"] is False
    invalid = citation_checks(CASE, "Najmanje 20 radnih dana [1][7].", SOURCES)
    assert invalid["invalid"] == [7] and invalid["cites_expected"] is False
    assert citation_checks(CASE, "Najmanje 20 radnih dana.", SOURCES)["uncited"]


def test_citation_checks_all_versus_any():
    case = {**CASE, "expected": ["najmanje 20 radnih dana", "najduže šest meseci"]}
    assert citation_checks(case, "20 dana [1].", SOURCES)["cites_expected"] is False
    assert citation_checks({**case, "match": "any"}, "20 dana [1].", SOURCES)["cites_expected"]
    assert citation_checks(case, "20 dana [1], šest meseci [2].", SOURCES)["cites_expected"]


def test_retrieval_scores():
    hits = [hit(1, "nešto drugo"), hit(2, "najmanje 20 radnih dana")]
    scores = retrieval_scores(CASE, hits)
    assert scores == {"hit": True, "recall": 1.0, "rr": 0.5, "ranks": [2]}
    both = {**CASE, "expected": ["najmanje 20 radnih dana", "šest meseci"]}
    assert retrieval_scores(both, hits)["hit"] is False
    assert retrieval_scores(both, hits)["recall"] == 0.5
    assert retrieval_scores({**both, "match": "any"}, hits)["hit"] is True


def result(**overrides) -> dict:
    base = {"passed": False, "answer_expected": True, "retrieval": {"hit": True},
            "judge": {"correct": False, "grounded": True}, "rules": {"abstained": False, "unsupported_numbers": []}}
    return {**base, **overrides}


def test_classify_root_causes():
    assert classify(result(passed=True)) is None
    assert classify(result(answer_expected=False, retrieval=None)) == "hallucination"
    assert classify(result(retrieval={"hit": False})) == "missed_retrieval"
    assert classify(result(judge={"correct": True, "grounded": True})) == "wrong_citation"
    assert classify(result(rules={"abstained": True, "unsupported_numbers": []})) == "false_abstention"
    assert classify(result(judge={"correct": False, "grounded": False})) == "hallucination"
    assert classify(result(rules={"abstained": False, "unsupported_numbers": ["25"]})) == "hallucination"
    assert classify(result()) == "incomplete_answer"


def test_parse_judgement():
    assert parse_judgement('```json\n{"correct": true, "grounded": false, "reason": "x"}\n```') == \
        {"correct": True, "grounded": False, "reason": "x"}
    assert parse_judgement("nonsense")["correct"] is False


def test_validate_cases():
    assert validate_cases([CASE]) == []
    errors = validate_cases([CASE, CASE, {"id": "x", "category": "nope", "question": "?", "answer": None, "expected": ["a"]}])
    assert "duplicate id t-1" in errors
    assert any("unknown category" in e for e in errors)
    assert any("cannot have expected" in e for e in errors)
    assert any("needs an expected passage" in e for e in validate_cases([{**CASE, "expected": []}]))


def test_abstention_with_past_tense():
    assert abstained("Ne mogao sam da pronađem odgovor u dokumentima.")


def test_page_numbers_from_passage_labels_are_supported():
    sources = [{**SOURCES[0], "source": "zakon.pdf, page 21"}]
    assert unsupported_numbers("Na strani 21 piše 20 radnih dana [1].", "Koliko?", sources) == []
