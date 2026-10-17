import pytest

from app.chunking import chunk_document, chunk_text, split_articles

LAW = """ZAKON O PRIMERU

Član 1
Ovim zakonom uređuju se prava i obaveze.

Član 2
Zaposleni ima pravo na odmor.

Član 2a
Dodatna odredba.
"""


def test_short_text_is_one_chunk():
    assert chunk_text("Kratak tekst.", size=100, overlap=10) == ["Kratak tekst."]


def test_empty_text_has_no_chunks():
    assert chunk_text("   \n\n  ", size=100, overlap=10) == []


def test_chunks_respect_size():
    text = " ".join(f"Rečenica broj {i}." for i in range(300))
    chunks = chunk_text(text, size=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_chunks_overlap():
    text = " ".join(f"reč{i}" for i in range(500))
    chunks = chunk_text(text, size=200, overlap=50)
    for previous, current in zip(chunks, chunks[1:]):
        assert current.split()[0] in previous


def test_whole_text_is_covered():
    words = [f"reč{i}" for i in range(500)]
    chunks = chunk_text(" ".join(words), size=200, overlap=50)
    covered = set(" ".join(chunks).split())
    assert set(words) <= covered


def test_prefers_sentence_boundaries():
    text = "Prva rečenica je ovde. " * 20
    chunks = chunk_text(text, size=100, overlap=20)
    assert all(c.endswith(".") for c in chunks)


def test_overlap_must_be_smaller_than_size():
    with pytest.raises(ValueError):
        chunk_text("tekst", size=50, overlap=50)


def test_split_articles():
    parts = split_articles(LAW)
    assert parts[0] == "ZAKON O PRIMERU"
    assert [p.splitlines()[0] for p in parts[1:]] == ["Član 1", "Član 2", "Član 2a"]


def test_article_mention_inside_sentence_does_not_split():
    text = "Član 1\nKao što je navedeno u Član 5 ovog zakona, pravilo važi."
    assert len(split_articles(text)) == 1


def test_chunk_document_never_mixes_articles():
    chunks = chunk_document(LAW, size=500, overlap=50)
    assert all(c.text.count("Član") <= 1 for c in chunks)


def test_heading_with_footnote_asterisk_still_splits():
    text = "Član 110.\nZarada se isplaćuje mesečno.\n3. Minimalna zarada\nČlan 111.*\nZaposleni ima pravo na minimalnu zaradu."
    assert [p.splitlines()[0] for p in split_articles(text)] == ["Član 110.", "Član 111.*"]


def test_long_article_continuations_carry_the_heading():
    article = "Član 7.\n" + " ".join(f"Rečenica broj {i}." for i in range(80))
    chunks = chunk_document(article, size=200, overlap=40)
    assert len(chunks) > 2
    assert chunks[0].text.startswith("Član 7.\n")
    assert all(c.text.startswith("Član 7. (nastavak)\n") for c in chunks[1:])


def test_cyrillic_continuation_label():
    article = "Члан 7.\n" + " ".join(f"Реченица број {i}." for i in range(80))
    chunks = chunk_document(article, size=200, overlap=40)
    assert chunks[1].text.startswith("Члан 7. (наставак)\n")


def test_chunk_start_offsets_point_into_the_text():
    from app.chunking import normalize
    text = normalize(LAW)
    for chunk in chunk_document(LAW, size=500, overlap=50):
        assert text[chunk.start:chunk.start + len(chunk.text)] == chunk.text


def test_heading_with_spaced_footnote_asterisk_splits():
    # The Zakon o radu PDF has "Члан 147. *": without this, article 147 was merged into article 146.
    text = "Члан 146.\nНадзор врши министарство.\nХ. ПРАВА ЗАПОСЛЕНИХ\nЧлан 147. *\nПослодавац следбеник преузима акт."
    assert [p.splitlines()[0] for p in split_articles(text)] == ["Члан 146.", "Члан 147. *"]
