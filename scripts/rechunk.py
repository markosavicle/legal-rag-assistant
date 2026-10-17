"""Re-chunk an indexed document with the current chunker, without the original file.

After a chunking fix, re-uploading is the normal path. When the original file is gone, the
document's text can be rebuilt from its stored chunks: continuation chunks repeat the article
heading and overlap the previous chunk, so both are removed and the pieces joined exactly.
Chunks whose text did not change reuse their cached embeddings; only new ones are embedded.

Page numbers are carried over from the old chunk each new chunk starts in.

Usage: python -m scripts.rechunk "Zakon o radu.pdf" [--dry-run]
"""
import argparse
import re
from bisect import bisect_right

from app import db, llm
from app.chunking import ARTICLE_HEADING, chunk_document
from app.config import settings
from app.stemmer import stem_text
from app.text import for_search

_CONTINUATION = re.compile(r"^(?:Član|Члан)[ \t]+\d+[a-zA-Zа-я]?\.?[ \t]*\((?:nastavak|наставак)\)\n")


def overlap(previous: str, current: str) -> int:
    """Length of the longest prefix of `current` that `previous` ends with."""
    for n in range(min(len(previous), len(current)), 0, -1):
        if previous.endswith(current[:n]):
            return n
    return 0


def rebuild_text(chunks: list[tuple[int | None, str]]) -> tuple[str, list[int], list[int | None]]:
    """Document text from (page, content) chunks in order, plus each old chunk's start offset and page."""
    text, starts, pages = "", [], []
    previous = None
    for page, content in chunks:
        body = _CONTINUATION.sub("", content, count=1)
        starts_article = body == content and ARTICLE_HEADING.match(content)
        if previous is not None and not starts_article:
            # A continuation (labelled, or of text before the first article): drop the shared part.
            starts.append(len(text) - overlap(previous, body))
            text += body[overlap(previous, body):]
        else:
            if text:
                text += "\n\n"
            starts.append(len(text))
            text += body
        pages.append(page)
        previous = body
    return text, starts, pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("filename")
    parser.add_argument("--dry-run", action="store_true", help="show what would change and stop")
    args = parser.parse_args()

    with db.connect() as conn:
        row = conn.execute("SELECT id FROM documents WHERE filename = %s", (args.filename,)).fetchone()
        if not row:
            raise SystemExit(f"Not indexed: {args.filename}")
        document_id = row[0]
        old = conn.execute("SELECT page, content FROM chunks WHERE document_id = %s ORDER BY chunk_index",
                           (document_id,)).fetchall()
        text, starts, pages = rebuild_text(old)
        new = chunk_document(text, settings.chunk_size, settings.chunk_overlap)
        new_pages = [pages[bisect_right(starts, c.start) - 1] for c in new]

        old_texts = {content for _, content in old}
        changed = [c.text for c in new if c.text not in old_texts]
        removed = [content for _, content in old if content not in {c.text for c in new}]
        print(f"{args.filename}: {len(old)} chunks -> {len(new)}; {len(changed)} new, {len(removed)} removed")
        for t in changed:
            print(f"  + {t[:100]!r}")
        for t in removed:
            print(f"  - {t[:100]!r}")
        if args.dry_run or not (changed or removed):
            return

        search_texts = [for_search(c.text) for c in new]
        embeddings, stats = llm.embed_texts(conn, search_texts)
        with conn.transaction():
            conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (document_id, chunk_index, page, content, search_text, stems, embedding) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [(document_id, i, page, c.text, s, stem_text(s), emb)
                     for i, (c, page, s, emb) in enumerate(zip(new, new_pages, search_texts, embeddings))],
                )
        print(f"Re-indexed: {stats.computed} embedded, {stats.cached} from cache")


if __name__ == "__main__":
    main()
