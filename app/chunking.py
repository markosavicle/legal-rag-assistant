import re

# Serbian legislation is structured as "Član 1", "Član 2a" ... on their own lines.
ARTICLE_HEADING = re.compile(r"(?=^[ \t]*Član[ \t]+\d+[a-zA-Z]?\.?[ \t]*$)", re.MULTILINE)

# Preferred break points, best first.
SEPARATORS = ("\n\n", ". ", "\n", " ")


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_articles(text: str) -> list[str]:
    """Split a legal text on article headings so a chunk never mixes two articles."""
    parts = [p.strip() for p in ARTICLE_HEADING.split(text)]
    return [p for p in parts if p]


def chunk_text(text: str, size: int = 800, overlap: int = 150) -> list[str]:
    """Split text into chunks of at most `size` characters with `overlap` characters of shared context.

    Cuts prefer paragraph, then sentence, then line, then word boundaries in the back half of the window.
    """
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    text = normalize(text)
    chunks: list[str] = []
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
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_document(text: str, size: int = 800, overlap: int = 150) -> list[str]:
    chunks: list[str] = []
    for article in split_articles(normalize(text)):
        chunks.extend(chunk_text(article, size, overlap))
    return chunks
