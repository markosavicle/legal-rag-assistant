from app.rag import build_messages
from app.search import Hit, build_or_tsquery, reciprocal_rank_fusion


def hit(chunk_id: int, score: float = 0.0) -> Hit:
    return Hit(chunk_id=chunk_id, filename="zakon.pdf", page=1, chunk_index=chunk_id, content=f"chunk {chunk_id}", score=score)


def test_rrf_rewards_agreement_between_retrievers():
    vector = [hit(1), hit(2), hit(3)]
    keyword = [hit(3), hit(4), hit(2)]
    fused = [h.chunk_id for h in reciprocal_rank_fusion([vector, keyword])]
    # 2 and 3 appear in both lists, so they beat 1 and 4 that appear once.
    assert set(fused[:2]) == {2, 3}
    assert set(fused) == {1, 2, 3, 4}


def test_rrf_single_list_keeps_order():
    fused = reciprocal_rank_fusion([[hit(5), hit(6), hit(7)]])
    assert [h.chunk_id for h in fused] == [5, 6, 7]


def test_rrf_scores_are_descending():
    fused = reciprocal_rank_fusion([[hit(1), hit(2)], [hit(2), hit(3)]])
    scores = [h.score for h in fused]
    assert scores == sorted(scores, reverse=True)


def test_or_tsquery_drops_short_words_question_words_and_duplicates():
    assert build_or_tsquery("Koliko traje godišnji odmor i odmor?") == "traj | godisnj | odmor"


def test_or_tsquery_empty():
    assert build_or_tsquery("a i u") is None


def test_prompt_numbers_sources():
    messages = build_messages("Pitanje?", [hit(1), hit(2)])
    user = messages[-1]["content"]
    assert "[1] (zakon.pdf, page 1)" in user
    assert "[2] (zakon.pdf, page 1)" in user
    assert user.endswith("Question: Pitanje?")


def test_or_tsquery_keeps_short_numbers():
    assert build_or_tsquery("Šta propisuje član 62?") == "propis | clan | 62"


def test_article_numbers_in_any_grammatical_case_and_script():
    from app.search import article_numbers
    assert article_numbers("Šta propisuje član 62?") == ["62"]
    assert article_numbers("Šta je uređeno članom 36 i člana 2a?") == ["36", "2a"]
    assert article_numbers("Шта каже члан 184?") == ["184"]
    assert article_numbers("Koliko traje godišnji odmor?") == []


def test_or_tsquery_matches_any_grammatical_form():
    assert build_or_tsquery("isplata zarade") == build_or_tsquery("isplatu zaradom")


def test_latin_question_gets_latin_answer():
    from app.rag import match_script
    assert match_script("Koliki je minuli rad?", "Najmanje 0,4% за сваку пуну годину [1].") == "Najmanje 0,4% za svaku punu godinu [1]."


def test_cyrillic_question_keeps_answer_as_is():
    from app.rag import match_script
    assert match_script("Колики је минули рад?", "Најмање 0,4% [1].") == "Најмање 0,4% [1]."


def test_article_lookup_keeps_the_first_article_with_a_number():
    from app.search import first_occurrences
    hits = [
        Hit(1, "zakon.pdf", 2, 15, "Član 11.\nNištavost odredaba.", 1.0),
        Hit(2, "zakon.pdf", 2, 16, "Član 11. (nastavak)\nnastavak teksta", 1.0),
        Hit(3, "zakon.pdf", 54, 371, "Član 11.\nPrelazna odredba izmena zakona.", 1.0),
        Hit(4, "ugovor.txt", None, 3, "Član 11.\nUgovorna odredba.", 1.0),
    ]
    assert [h.chunk_id for h in first_occurrences(hits)] == [1, 2, 4]
