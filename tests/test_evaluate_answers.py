from scripts.evaluate_answers import cited_numbers, cites_expected, parse_verdict

SOURCES = [
    {"n": 1, "text": "Član 69.\nZaposleni ima pravo na godišnji odmor ... najmanje 20 radnih dana."},
    {"n": 2, "text": "Član 36.\nProbni rad može da traje najduže šest meseci."},
]


def test_parse_verdict_plain_json():
    assert parse_verdict('{"correct": true, "reason": "Same facts."}') == (True, "Same facts.")


def test_parse_verdict_inside_code_fence():
    assert parse_verdict('```json\n{"correct": false, "reason": "Wrong number."}\n```') == (False, "Wrong number.")


def test_parse_verdict_garbage_counts_as_incorrect():
    correct, reason = parse_verdict("I think it is right")
    assert correct is False and "could not be parsed" in reason


def test_cited_numbers():
    assert cited_numbers("Najmanje 20 dana [1], vidi i [3][1].") == {1, 3}


def test_cites_expected_when_the_right_passage_is_cited():
    assert cites_expected("Najmanje 20 radnih dana [1].", SOURCES, "najmanje 20 radnih dana")


def test_cites_expected_fails_when_another_passage_is_cited():
    assert not cites_expected("Najmanje 20 radnih dana [2].", SOURCES, "najmanje 20 radnih dana")


def test_cites_expected_matches_across_scripts():
    sources = [{"n": 1, "text": "Члан 69.\nнајмање 20 радних дана"}]
    assert cites_expected("Najmanje 20 radnih dana [1].", sources, "najmanje 20 radnih dana")


def test_cited_numbers_with_comma_lists():
    assert cited_numbers("Dve prosečne zarade [1, 2]. Vidi [3,4].") == {1, 2, 3, 4}
