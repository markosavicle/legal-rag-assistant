import hashlib
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from openai import AzureOpenAI, OpenAI

from app.config import settings

EMBEDDING_BATCH_SIZE = 100


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    if settings.azure_endpoint:
        return AzureOpenAI(
            azure_endpoint=settings.azure_endpoint,
            api_key=settings.azure_api_key,
            api_version=settings.azure_api_version,
        )
    return OpenAI(api_key=settings.openai_api_key)


@dataclass
class EmbeddingStats:
    cached: int = 0
    computed: int = 0
    tokens: int = 0


def _cache_key(text: str) -> str:
    return hashlib.sha256(f"{settings.embedding_model}\n{text}".encode("utf-8")).hexdigest()


def embed_texts(conn, texts: list[str]) -> tuple[list[np.ndarray], EmbeddingStats]:
    """Embed texts, reusing cached vectors from Postgres and batching the rest."""
    stats = EmbeddingStats()
    keys = [_cache_key(t) for t in texts]

    rows = conn.execute(
        "SELECT text_hash, embedding FROM embedding_cache WHERE text_hash = ANY(%s)", (keys,)
    ).fetchall()
    vectors: dict[str, np.ndarray] = {key: emb for key, emb in rows}

    missing = list(dict.fromkeys(k for k in keys if k not in vectors))
    stats.cached = len(texts) - sum(1 for k in keys if k in missing)
    text_by_key = dict(zip(keys, texts))

    for start in range(0, len(missing), EMBEDDING_BATCH_SIZE):
        batch = missing[start:start + EMBEDDING_BATCH_SIZE]
        response = get_client().embeddings.create(
            model=settings.embedding_model, input=[text_by_key[k] for k in batch]
        )
        stats.tokens += response.usage.total_tokens
        for key, item in zip(batch, response.data):
            embedding = np.array(item.embedding, dtype=np.float32)
            vectors[key] = embedding
            conn.execute(
                "INSERT INTO embedding_cache (text_hash, model, embedding) VALUES (%s, %s, %s) "
                "ON CONFLICT (text_hash) DO NOTHING",
                (key, settings.embedding_model, embedding),
            )
        stats.computed += len(batch)

    return [vectors[k] for k in keys], stats


def embed_query(conn, text: str) -> np.ndarray:
    vectors, _ = embed_texts(conn, [text])
    return vectors[0]


def chat(messages: list[dict]) -> tuple[str, dict]:
    response = get_client().chat.completions.create(
        model=settings.chat_model, messages=messages, temperature=0
    )
    usage = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
    }
    return response.choices[0].message.content, usage
