import re
from dataclasses import dataclass

# Reciprocal Rank Fusion constant from the original paper (Cormack et al., 2009).
RRF_K = 60
# Each retriever fetches more candidates than we return, so fusion has something to work with.
CANDIDATE_MULTIPLIER = 4

MODES = ("vector", "keyword", "hybrid")


@dataclass
class Hit:
    chunk_id: int
    filename: str
    page: int | None
    chunk_index: int
    content: str
    score: float


_SELECT = "SELECT c.id, d.filename, c.page, c.chunk_index, c.content, {score} AS score FROM chunks c JOIN documents d ON d.id = c.document_id"


def vector_search(conn, query_embedding, k: int) -> list[Hit]:
    rows = conn.execute(
        _SELECT.format(score="1 - (c.embedding <=> %(q)s)") + " ORDER BY c.embedding <=> %(q)s LIMIT %(k)s",
        {"q": query_embedding, "k": k},
    ).fetchall()
    return [Hit(*row) for row in rows]


def build_or_tsquery(query: str) -> str | None:
    """Turn a natural-language question into an OR tsquery, so a chunk does not need every word to match."""
    terms = dict.fromkeys(t for t in re.findall(r"\w+", query.lower()) if len(t) > 2)
    return " | ".join(terms) or None


def keyword_search(conn, query: str, k: int) -> list[Hit]:
    tsquery = build_or_tsquery(query)
    if tsquery is None:
        return []
    rows = conn.execute(
        _SELECT.format(score="ts_rank_cd(c.tsv, to_tsquery('simple', %(q)s))")
        + " WHERE c.tsv @@ to_tsquery('simple', %(q)s) ORDER BY score DESC LIMIT %(k)s",
        {"q": tsquery, "k": k},
    ).fetchall()
    return [Hit(*row) for row in rows]


def reciprocal_rank_fusion(result_lists: list[list[Hit]], k: int = RRF_K) -> list[Hit]:
    """Merge ranked lists by summing 1 / (k + rank). Rewards chunks that rank well in several retrievers."""
    scores: dict[int, float] = {}
    hits: dict[int, Hit] = {}
    for results in result_lists:
        for rank, hit in enumerate(results, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
            hits.setdefault(hit.chunk_id, hit)
    fused = sorted(scores, key=scores.get, reverse=True)
    return [Hit(**{**hits[cid].__dict__, "score": scores[cid]}) for cid in fused]


def search(conn, query: str, query_embedding, k: int, mode: str = "hybrid") -> list[Hit]:
    if mode == "vector":
        return vector_search(conn, query_embedding, k)
    if mode == "keyword":
        return keyword_search(conn, query, k)
    if mode == "hybrid":
        candidates = k * CANDIDATE_MULTIPLIER
        return reciprocal_rank_fusion([
            vector_search(conn, query_embedding, candidates),
            keyword_search(conn, query, candidates),
        ])[:k]
    raise ValueError(f"Unknown search mode: {mode}")
