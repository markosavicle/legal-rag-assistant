from app.rag import (
    REFUSAL_SR_CYRILLIC, REFUSAL_SR_LATIN, answer_status, is_english, localize_refusal,
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


def test_english_question_keeps_english_refusal():
    question = "What is the VAT rate in Serbia?"
    assert is_english(question)
    assert localize_refusal(question, ENGLISH_REFUSALS[0]) == ENGLISH_REFUSALS[0]


def test_serbian_questions_are_not_english():
    for question in ["Koliko najmanje traje godišnji odmor?", "Šta propisuje član 62?", "Kolika je zarada?",
                     "Da li je otkazni rok od 15 dana u skladu sa Zakonom o radu?",
                     # "do" and "a" are Serbian words too (cf-06, cmp-02)
                     "Ugovor Ane Jović kaže da se zarada isplaćuje do 10. u mesecu, a zakon do kraja meseca. Koji rok važi?",
                     "Koliko dana godišnjeg odmora ima Ana Jović, a koliko Nikola Ilić?"]:
        assert not is_english(question)


def test_answers_and_serbian_refusals_are_left_alone():
    question = "Koliko dana godišnjeg odmora ima Ana Jović?"
    for answer in ["Godišnji odmor traje najmanje 20 radnih dana [1].",
                   "Ne mogao sam da pronađem odgovor u dokumentima.",
                   "Za Nikolu Ilića u dokumentima piše samo da je iz Beograda, dok adresa nije navedena [1]."]:
        assert localize_refusal(question, answer) == answer


def test_localized_refusals_still_count_as_unanswered():
    assert answer_status(REFUSAL_SR_LATIN, 5) == (False, [])
    assert answer_status(REFUSAL_SR_CYRILLIC, 5) == (False, [])
