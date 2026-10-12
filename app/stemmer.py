"""A light Serbian stemmer for keyword search.

Serbian words change their ending with grammatical case, number and tense: odmor, odmora,
odmoru, odmorom. Exact keyword matching treats those as different words. This stemmer cuts
one common inflectional ending so they all index as "odmor".

It is deliberately simple (one suffix, longest first, stem of at least 3 letters). It does not
handle sound changes inside the stem (isplati / isplaćuje); semantic search covers those.
Stems are also folded to ASCII, so questions typed without diacritics (godisnji) still match.
"""
import re

_SUFFIXES = sorted({
    # adjective and pronoun endings
    "ijega", "ijemu", "ijima", "ijeg", "ijem", "ijih", "ijim", "ijoj", "ijom", "ije", "iji", "iju",
    "ega", "emu", "oga", "omu", "ome", "eg", "og", "em", "om", "im", "ih", "oj",
    # noun plural and case endings
    "ovima", "evima", "ova", "ove", "ovi", "ovu", "eva", "eve", "evi", "ama", "ima",
    # verb endings
    "ujemo", "ujete", "ujući", "ajući", "ujem", "uje", "uju", "ati", "iti", "eti", "uti",
    "ala", "alo", "ali", "ila", "ilo", "ili", "ela", "elo", "eli", "emo", "ete", "eš",
    # single vowels last
    "a", "e", "i", "o", "u",
}, key=len, reverse=True)

MIN_STEM = 3

_FOLD = str.maketrans({"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "dj"})


def stem(word: str) -> str:
    word = word.lower()
    if not word.isdigit():
        for suffix in _SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= MIN_STEM:
                word = word[: -len(suffix)]
                break
    return word.translate(_FOLD)


def stem_text(text: str) -> str:
    """Stem every word of a (Latin-script) text, for the full-text index."""
    return " ".join(stem(w) for w in re.findall(r"\w+", text))
