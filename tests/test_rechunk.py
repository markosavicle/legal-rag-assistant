from app.chunking import chunk_document, normalize
from scripts.rechunk import overlap, rebuild_text

LAW = "ZAKON O PRIMERU\n\n" + "\n".join(
    f"Član {n}.\n" + " ".join(f"Rečenica {n}-{i} o pravima zaposlenih." for i in range(n * 7)) for n in range(1, 6)
)


def test_overlap():
    assert overlap("abc def", "def ghi") == 3
    assert overlap("abc", "xyz") == 0


def test_rebuilt_text_chunks_exactly_like_the_original():
    chunks = chunk_document(LAW, size=300, overlap=60)
    text, starts, pages = rebuild_text([(1, c.text) for c in chunks])
    assert [c.text for c in chunk_document(text, size=300, overlap=60)] == [c.text for c in chunks]
    assert len(starts) == len(pages) == len(chunks)


def test_rebuilt_text_keeps_every_word():
    chunks = chunk_document(LAW, size=300, overlap=60)
    text, _, _ = rebuild_text([(None, c.text) for c in chunks])
    assert text.split() == normalize(LAW).split()
