"""Ingest every supported file in a folder.

Usage: python -m scripts.ingest_dir data/
"""
import sys
from pathlib import Path

from app import db
from app.ingest import SUPPORTED, ingest_file


def main(folder: str) -> None:
    db.init_db()
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in SUPPORTED)
    if not files:
        sys.exit(f"No supported files in {folder} ({', '.join(sorted(SUPPORTED))})")
    with db.connect() as conn:
        for path in files:
            result = ingest_file(conn, path)
            print(
                f"{result['filename']}: {result['chunks']} chunks, "
                f"{result['embeddings_computed']} embedded ({result['embedding_tokens']} tokens), "
                f"{result['embeddings_cached']} from cache"
            )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")
