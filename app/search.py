import re
from dataclasses import dataclass

from app.stemmer import stem
from app.text import for_search

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


def _in_scope(documents: list[int] | None) -> str:
    """SQL condition limiting a search to the selected documents (all documents when None)."""
    return "c.document_id = ANY(%(documents)s)" if documents else "TRUE"


def vector_search(conn, query_embedding, k: int, documents: list[int] | None = None) -> list[Hit]:
    rows = conn.execute(
        _SELECT.format(score="1 - (c.embedding <=> %(q)s)")
        + f" WHERE {_in_scope(documents)} ORDER BY c.embedding <=> %(q)s LIMIT %(k)s",
        {"q": query_embedding, "k": k, "documents": documents},
    ).fetchall()
    return [Hit(*row) for row in rows]


# Question words that appear in almost every question but say nothing about the topic.
# (Words of 1-2 letters are dropped anyway.)
STOPWORDS = {
    "koliko", "koji", "koja", "koje", "kojeg", "kojem", "kojim", "kojoj", "kojih", "kako", "kada",
    "gde", "šta", "što", "zašto", "čemu", "kome", "koga", "može", "mogu", "sme", "ima", "imaju",
    "ili", "ako", "biti", "jeste", "nije", "ovog", "ovaj", "ova", "ovo", "taj", "neki", "neka",
}


def build_or_tsquery(query: str) -> str | None:
    """Turn a natural-language question into an OR tsquery of stems, so a chunk does not need every
    word to match and any grammatical form of a word matches the others.

    The index is built from stemmed Latin-script text, so the query is transliterated and stemmed the same way.
    """
    words = re.findall(r"\w+", for_search(query).lower())
    # Numbers are kept whatever their length: "član 62" is all about the 62.
    terms = dict.fromkeys(stem(w) for w in words if (len(w) > 2 or w.isdigit()) and w not in STOPWORDS)
    return " | ".join(terms) or None


# "član 62", "članom 36", "člana 2a" in a question.
ARTICLE_REFERENCE = re.compile(r"\bčlan\w*\s+(\d+[a-z]?)\b")


def article_numbers(query: str) -> list[str]:
    return list(dict.fromkeys(ARTICLE_REFERENCE.findall(for_search(query).lower())))


def article_lookup(conn, query: str, k: int, documents: list[int] | None = None) -> list[Hit]:
    """Chunks of the articles a question names explicitly. Every chunk starts with its article heading."""
    numbers = article_numbers(query)
    if not numbers:
        return []
    rows = conn.execute(
        _SELECT.format(score="1.0")
        + f" WHERE c.search_text ~* %(pattern)s AND {_in_scope(documents)} ORDER BY c.document_id, c.chunk_index LIMIT %(k)s",
        {"pattern": rf"^član ({'|'.join(numbers)})\.?(\s|$)", "k": k, "documents": documents},
    ).fetchall()
    return [Hit(*row) for row in rows]


def full_text_search(conn, query: str, k: int, documents: list[int] | None = None) -> list[Hit]:
    tsquery = build_or_tsquery(query)
    if tsquery is None:
        return []
    rows = conn.execute(
        _SELECT.format(score="ts_rank_cd(c.tsv, to_tsquery('simple', %(q)s))")
        + f" WHERE c.tsv @@ to_tsquery('simple', %(q)s) AND {_in_scope(documents)} ORDER BY score DESC LIMIT %(k)s",
        {"q": tsquery, "k": k, "documents": documents},
    ).fetchall()
    return [Hit(*row) for row in rows]


def keyword_search(conn, query: str, k: int, documents: list[int] | None = None) -> list[Hit]:
    """Exact matching: articles named in the question first, then full-text matches."""
    hits = {h.chunk_id: h for h in article_lookup(conn, query, k, documents)}
    for hit in full_text_search(conn, query, k, documents):
        hits.setdefault(hit.chunk_id, hit)
    return list(hits.values())[:k]


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


def search(conn, query: str, query_embedding, k: int, mode: str = "vector", documents: list[int] | None = None) -> list[Hit]:
    """Retrieve the top k chunks. `documents` limits the search to those document ids (None = all)."""
    if mode == "vector":
        return vector_search(conn, query_embedding, k, documents)
    if mode == "keyword":
        return keyword_search(conn, query, k, documents)
    if mode == "hybrid":
        candidates = k * CANDIDATE_MULTIPLIER
        return reciprocal_rank_fusion([
            vector_search(conn, query_embedding, candidates, documents),
            keyword_search(conn, query, candidates, documents),
        ])[:k]
    raise ValueError(f"Unknown search mode: {mode}")
