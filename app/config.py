import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag"))

    # Plain OpenAI is used unless an Azure OpenAI endpoint is configured.
    # OPENAI_BASE_URL points the same client at any OpenAI-compatible API (Gemini, Ollama, ...).
    openai_api_key: str | None = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_base_url: str | None = field(default_factory=lambda: _env("OPENAI_BASE_URL"))
    azure_endpoint: str | None = field(default_factory=lambda: _env("AZURE_OPENAI_ENDPOINT"))
    azure_api_key: str | None = field(default_factory=lambda: _env("AZURE_OPENAI_API_KEY"))
    azure_api_version: str = field(default_factory=lambda: _env("AZURE_OPENAI_API_VERSION", "2024-10-21"))

    # With Azure these are deployment names rather than model names.
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "text-embedding-3-small"))
    embedding_dim: int = field(default_factory=lambda: int(_env("EMBEDDING_DIM", "1536")))
    chat_model: str = field(default_factory=lambda: _env("CHAT_MODEL", "gpt-4o-mini"))
    # Texts embedded per minute at most (0 = no limit). Free tiers count every text as one request.
    embedding_rpm: int = field(default_factory=lambda: int(_env("EMBEDDING_REQUESTS_PER_MINUTE", "0")))
    chat_rpm: int = field(default_factory=lambda: int(_env("CHAT_REQUESTS_PER_MINUTE", "0")))

    chunk_size: int = field(default_factory=lambda: int(_env("CHUNK_SIZE", "800")))
    chunk_overlap: int = field(default_factory=lambda: int(_env("CHUNK_OVERLAP", "150")))
    top_k: int = field(default_factory=lambda: int(_env("TOP_K", "5")))

    # When set, every API call must send it in the X-API-Key header (the web page asks for it once).
    # Leave empty for local use; set it before exposing the API to n8n or anything on a network.
    api_key: str | None = field(default_factory=lambda: _env("API_KEY"))


settings = Settings()
