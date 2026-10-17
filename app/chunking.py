import re
from dataclasses import dataclass

# Serbian legislation is structured as "Član 1", "Član 2a" (or Cyrillic "Члан 1.") on their own lines,
# sometimes followed by footnote asterisks marking amendments ("Član 111.*").
# The asterisk may be separated by a space ("Члан 147. *").
_HEADING = r"(?:Član|Члан)[ \t]+\d+[a-zA-Zа-я]?\.?"
ARTICLE_HEADING = re.compile(rf"^[ \t]*({_HEADING})[ \t]*\**[ \t]*$", re.MULTILINE)

# Preferred break points, best first.
SEPARATORS = ("\n\n", ". ", "\n", " ")


@dataclass(frozen=True)
class Chunk:
    start: int  # offset in the normalised document text, used to find the page
    text: str


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _article_starts(text: str) -> list[int]:
    return sorted({0, *(m.start() for m in ARTICLE_HEADING.finditer(text))})


def split_articles(text: str) -> list[str]:
    """Split a legal text on article headings so a chunk never mixes two articles."""
    starts = _article_starts(text)
    parts = [text[a:b].strip() for a, b in zip(starts, starts[1:] + [len(text)])]
    return [p for p in parts if p]


def chunk_spans(text: str, size: int = 800, overlap: int = 150) -> list[tuple[int, int]]:
    """(start, end) spans of at most `size` characters with `overlap` characters of shared context.

    Cuts prefer paragraph, then sentence, then line, then word boundaries in the back half of the window.
    """
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            for sep in SEPARATORS:
                cut = window.rfind(sep)
                if cut > size // 2:
                    end = start + cut + len(sep)
                    break
        s, e = start, end
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            spans.append((s, e))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return spans


def chunk_text(text: str, size: int = 800, overlap: int = 150) -> list[str]:
    text = normalize(text)
    return [text[s:e] for s, e in chunk_spans(text, size, overlap)]


def chunk_document(text: str, size: int = 800, overlap: int = 150) -> list[Chunk]:
    """Chunk a whole document article by article.

    When a long article needs several chunks, the later ones are prefixed with the article
    heading, so every chunk says which article it belongs to (for citations and keyword search).
    """
    text = normalize(text)
    starts = _article_starts(text)
    chunks: list[Chunk] = []
    for a, b in zip(starts, starts[1:] + [len(text)]):
        article = text[a:b]
        match = ARTICLE_HEADING.match(article)
        heading = match.group(1) if match else None
        for i, (s, e) in enumerate(chunk_spans(article, size, overlap)):
            body = article[s:e]
            if i > 0 and heading:
                continued = "(наставак)" if heading.startswith("Члан") else "(nastavak)"
                body = f"{heading} {continued}\n{body}"
            chunks.append(Chunk(a + s, body))
    return chunks
