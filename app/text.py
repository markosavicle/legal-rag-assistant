"""Text normalisation for retrieval.

Serbian is written in both Cyrillic and Latin script, and the two map one-to-one.
Everything used for retrieval (embeddings, the full-text index, queries) goes through
for_search(), so a question in either script finds a document in either script. The
original text is kept for display and for the LLM.
"""
import re

_CYRILLIC = "абвгдђежзијклљмнњопрстћуфхцчџш"
_LATIN = ["a", "b", "v", "g", "d", "đ", "e", "ž", "z", "i", "j", "k", "l", "lj", "m", "n", "nj",
          "o", "p", "r", "s", "t", "ć", "u", "f", "h", "c", "č", "dž", "š"]

_TABLE = {}
for cyr, lat in zip(_CYRILLIC, _LATIN):
    _TABLE[ord(cyr)] = lat
    _TABLE[ord(cyr.upper())] = lat.capitalize()

# Official consolidated texts mark amended passages with footnote asterisks inside sentences
# ("dve* prosečne zarade"), which would otherwise break phrase and keyword matching.
_FOOTNOTE_MARKS = re.compile(r"\*+")


def to_latin(text: str) -> str:
    return text.translate(_TABLE)


def for_search(text: str) -> str:
    text = _FOOTNOTE_MARKS.sub("", to_latin(text))
    return re.sub(r"[ \t]+", " ", text).strip()
