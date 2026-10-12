from app.chunking import split_articles
from app.search import build_or_tsquery
from app.text import for_search, to_latin


def test_to_latin_single_letters():
    assert to_latin("Запослени има право на годишњи одмор") == "Zaposleni ima pravo na godišnji odmor"


def test_to_latin_digraphs_and_capitals():
    assert to_latin("љубав њива џеп") == "ljubav njiva džep"
    assert to_latin("Љубав Њива Џеп") == "Ljubav Njiva Džep"


def test_to_latin_leaves_latin_and_digits_alone():
    text = "Član 69. — 20 radnih dana"
    assert to_latin(text) == text


def test_cyrillic_and_latin_questions_give_same_tsquery():
    assert build_or_tsquery("Колико траје пробни рад?") == build_or_tsquery("Koliko traje probni rad?")


def test_split_cyrillic_articles():
    text = "ЗАКОН О РАДУ\n\nЧлан 1.\nОвим законом уређују се права.\n\nЧлан 2.\nОдредбе.\n\nЧлан 2а\nДодатак."
    parts = split_articles(text)
    assert [p.splitlines()[0] for p in parts[1:]] == ["Члан 1.", "Члан 2.", "Члан 2а"]


def test_for_search_removes_footnote_marks():
    assert for_search("najmanje u visini dve* prosečne zarade**") == "najmanje u visini dve prosečne zarade"


def test_for_search_transliterates():
    assert for_search("Члан 111.*") == "Član 111."
