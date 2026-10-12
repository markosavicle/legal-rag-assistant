from bisect import bisect_right

from app.chunking import chunk_document
from app.ingest import join_pages


def page_of(chunk, starts, numbers):
    return numbers[bisect_right(starts, chunk.start) - 1]


def test_article_crossing_a_page_break_stays_together():
    pages = [
        (1, "Član 1.\nPrvi deo prvog člana koji se nastavlja"),
        (2, "na sledećoj strani.\n\nČlan 2.\nDrugi član."),
    ]
    text, starts, numbers = join_pages(pages)
    chunks = chunk_document(text, size=800, overlap=100)
    assert [c.text.splitlines()[0] for c in chunks] == ["Član 1.", "Član 2."]
    assert "nastavlja\n\nna sledećoj strani" in chunks[0].text
    assert [page_of(c, starts, numbers) for c in chunks] == [1, 2]


def test_empty_pages_are_skipped():
    text, starts, numbers = join_pages([(1, "Član 1.\nTekst."), (2, "   "), (3, "Član 2.\nJoš teksta.")])
    assert numbers == [1, 3]
    chunks = chunk_document(text)
    assert [page_of(c, starts, numbers) for c in chunks] == [1, 3]


def test_single_text_document_has_no_page():
    text, starts, numbers = join_pages([(None, "Član 1.\nTekst.")])
    assert [page_of(c, starts, numbers) for c in chunk_document(text)] == [None]
