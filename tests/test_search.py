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


def test_or_tsquery_drops_short_words_and_duplicates():
    assert build_or_tsquery("Koliko traje godišnji odmor i odmor?") == "koliko | traje | godišnji | odmor"


def test_or_tsquery_empty():
    assert build_or_tsquery("a i u") is None


def test_prompt_numbers_sources():
    messages = build_messages("Pitanje?", [hit(1), hit(2)])
    user = messages[-1]["content"]
    assert "[1] (zakon.pdf, page 1)" in user
    assert "[2] (zakon.pdf, page 1)" in user
    assert user.endswith("Question: Pitanje?")
