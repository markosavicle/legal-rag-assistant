import pytest

from app.stemmer import stem, stem_text


@pytest.mark.parametrize("forms", [
    ["odmor", "odmora", "odmoru", "odmorom"],
    ["zarada", "zarade", "zaradu", "zaradom"],
    ["godišnji", "godišnjeg", "godišnjem", "godisnji"],
    ["radnih", "radni", "radna", "radnom"],
    ["časova", "časa", "časove"],
    ["meseci", "meseca", "mesec"],
    ["prekovremeni", "prekovremenog", "prekovremenom"],
    ["porodiljsko", "porodiljskog", "porodiljskom"],
])
def test_inflected_forms_share_a_stem(forms):
    assert len({stem(f) for f in forms}) == 1, {f: stem(f) for f in forms}


def test_short_words_are_left_alone():
    assert stem("dva") == "dva"
    assert stem("rad") == "rad"


def test_numbers_are_left_alone():
    assert stem("62") == "62"
    assert stem("2024") == "2024"


def test_diacritics_are_folded():
    assert stem("čas") == "cas"
    assert stem("đak") == "djak"


def test_stem_text():
    assert stem_text("Zaposleni ima pravo na godišnji odmor") == "zaposlen ima prav na godisnj odmor"
