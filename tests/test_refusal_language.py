from app.rag import (
    REFUSAL_EN, REFUSAL_SR_CYRILLIC, REFUSAL_SR_LATIN, answer_status, is_english, is_pure_refusal,
    localize_refusal,
)

# Real answers from eval/runs/final/results.json (oos-02, oos-04, fp-02).
ENGLISH_REFUSALS = [
    "Could not find the answer in the documents.",
    "could not find the answer in the documents.",
    "I could not find anything relevant in the uploaded documents.",
]


def test_english_refusal_to_latin_question_becomes_serbian_latin():
    for refusal in ENGLISH_REFUSALS:
        assert localize_refusal("Kolika je stopa PDV-a u Srbiji?", refusal) == REFUSAL_SR_LATIN


def test_english_refusal_to_cyrillic_question_becomes_serbian_cyrillic():
    assert localize_refusal("Колика је стопа ПДВ-а?", ENGLISH_REFUSALS[0]) == REFUSAL_SR_CYRILLIC


def test_english_question_gets_fixed_english_refusal():
    question = "What is the VAT rate in Serbia?"
    assert is_english(question)
    for refusal in ENGLISH_REFUSALS:
        assert localize_refusal(question, refusal) == REFUSAL_EN


def test_serbian_questions_are_not_english():
    for question in ["Koliko najmanje traje godišnji odmor?", "Šta propisuje član 62?", "Kolika je zarada?",
                     "Da li je otkazni rok od 15 dana u skladu sa Zakonom o radu?",
                     # "do" and "a" are Serbian words too (cf-06, cmp-02)
                     "Ugovor Ane Jović kaže da se zarada isplaćuje do 10. u mesecu, a zakon do kraja meseca. Koji rok važi?",
                     "Koliko dana godišnjeg odmora ima Ana Jović, a koliko Nikola Ilić?"]:
        assert not is_english(question)


def test_answers_and_partial_answers_are_left_alone():
    question = "Koliko dana godišnjeg odmora ima Ana Jović?"
    for answer in ["Godišnji odmor traje najmanje 20 radnih dana [1].",
                   "Za Nikolu Ilića u dokumentima piše samo da je iz Beograda, dok adresa nije navedena [1].",
                   # oos-07: a partial answer with a number must keep its facts and citation
                   "U dostavljenim dokumentima se navodi samo bruto zarada Nikole Ilića koja iznosi "
                   "145.000,00 dinara, dok podatak o neto zaradi nije naveden [2].",
                   "Nisam pronašao podatak o neto zaradi, ali bruto zarada iznosi 145.000,00 dinara [2]."]:
        assert not is_pure_refusal(answer)
        assert localize_refusal(question, answer) == answer


def test_ungrammatical_serbian_refusal_is_fixed_and_drops_citations():
    # oos-01 in eval/runs/final/results.json
    raw = "Ne mogao sam da pronađem odgovor u dokumentima [1][2][3][4][5]."
    assert localize_refusal("Koja je kazna za prebrzu vožnju?", raw) == REFUSAL_SR_LATIN
    assert localize_refusal("Која је казна за пребрзу вожњу?", "Не могао сам да пронађем одговор у документима [1].") \
        == REFUSAL_SR_CYRILLIC
    for raw in ["Nisam mogao da pronađem odgovor u dokumentima.", "Nisam uspeo da nađem odgovor u dokumentima [2]."]:
        assert localize_refusal("Kolika je stopa PDV-a?", raw) == REFUSAL_SR_LATIN


def test_localized_refusals_still_count_as_unanswered():
    assert answer_status(REFUSAL_SR_LATIN, 5) == (False, [])
    assert answer_status(REFUSAL_SR_CYRILLIC, 5) == (False, [])
    assert answer_status(REFUSAL_EN, 5) == (False, [])
