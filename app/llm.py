import hashlib
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from openai import AzureOpenAI, OpenAI, RateLimitError

from app.config import settings
from app.text import for_search

log =logging.getLogger("uvicorn.error")

EMBEDDING_BATCH_SIZE = 100
# The client retries transient errors (including short 429s) with exponential backoff.
MAX_RETRIES = 6
# Per-minute quotas need a longer wait than the client's backoff covers.
RATE_LIMIT_WAIT_SECONDS = 30
RATE_LIMIT_ATTEMPTS = 4


class RateLimiter:
    """Sliding one-minute window over how many texts were sent, so we stay under a provider quota."""

    def __init__(self, per_minute: int, clock=time.monotonic, sleep=time.sleep):
        self.per_minute = per_minute
        self.clock = clock
        self.sleep = sleep
        self.sent: deque[tuple[float, int]] = deque()
        self.lock = threading.Lock()

    def acquire(self, count: int) -> None:
        if not self.per_minute:
            return
        if count > self.per_minute:
            raise ValueError(f"Cannot send {count} texts at once with a limit of {self.per_minute} per minute")
        with self.lock:
            while True:
                now = self.clock()
                while self.sent and now - self.sent[0][0] >= 60:
                    self.sent.popleft()
                if sum(c for _, c in self.sent) + count <= self.per_minute:
                    break
                self.sleep(60 - (now - self.sent[0][0]) + 0.5)
            self.sent.append((self.clock(), count))


embedding_limiter = RateLimiter(settings.embedding_rpm)
chat_limiter = RateLimiter(settings.chat_rpm)


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    if settings.azure_endpoint:
        return AzureOpenAI(
            azure_endpoint=settings.azure_endpoint,
            api_key=settings.azure_api_key,
            api_version=settings.azure_api_version,
            max_retries=MAX_RETRIES,
        )
    # Local servers such as Ollama ignore the key, but the client requires one.
    api_key = settings.openai_api_key or ("not-needed" if settings.openai_base_url else None)
    return OpenAI(api_key=api_key, base_url=settings.openai_base_url, max_retries=MAX_RETRIES)


def provider_name() -> str:
    if settings.azure_endpoint:
        return "Azure OpenAI"
    url = settings.openai_base_url or ""
    if "generativelanguage.googleapis.com" in url:
        return "Google Gemini"
    if "11434" in url or "ollama" in url:
        return "Ollama (local)"
    return "OpenAI-compatible" if url else "OpenAI"


def _tokens(usage, field: str) -> int:
    # Not every OpenAI-compatible server reports usage.
    return getattr(usage, field, None) or 0


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

    batch_size = min(EMBEDDING_BATCH_SIZE, settings.embedding_rpm or EMBEDDING_BATCH_SIZE)
    for start in range(0, len(missing), batch_size):
        batch = missing[start:start + batch_size]
        if len(missing) > batch_size:
            log.info("Embedding %d-%d of %d new chunks", start + 1, start + len(batch), len(missing))
        texts_in_batch = [text_by_key[k] for k in batch]
        response = _within_quota(
            embedding_limiter, len(batch), "Embedding",
            lambda: get_client().embeddings.create(model=settings.embedding_model, input=texts_in_batch),
        )
        stats.tokens += _tokens(response.usage, "total_tokens")
        # Each batch is cached as soon as it arrives, so a failed upload resumes where it stopped.
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


def is_daily_quota(error: Exception) -> bool:
    return "PerDay" in str(error)


def _within_quota(limiter: RateLimiter, count: int, what: str, call):
    """Pace a provider call through `limiter`, and wait out per-minute quota errors."""
    for attempt in range(1, RATE_LIMIT_ATTEMPTS + 1):
        limiter.acquire(count)
        try:
            return call()
        except RateLimitError as e:
            # A daily quota resets hours later, so waiting and retrying is pointless.
            if attempt == RATE_LIMIT_ATTEMPTS or is_daily_quota(e):
                raise
            log.warning("%s quota reached, waiting %ss (attempt %d)", what, RATE_LIMIT_WAIT_SECONDS, attempt)
            time.sleep(RATE_LIMIT_WAIT_SECONDS)


def embed_query(conn, text: str) -> np.ndarray:
    # Chunks are embedded in Latin script, so the question must be too.
    vectors, _ = embed_texts(conn, [for_search(text)])
    return vectors[0]


def chat(messages: list[dict], model: str | None = None) -> tuple[str, dict]:
    response = _within_quota(
        chat_limiter, 1, "Chat",
        lambda: get_client().chat.completions.create(model=model or settings.chat_model, messages=messages, temperature=0),
    )
    usage = {
        "prompt_tokens": _tokens(response.usage, "prompt_tokens"),
        "completion_tokens": _tokens(response.usage, "completion_tokens"),
    }
    return response.choices[0].message.content, usage
