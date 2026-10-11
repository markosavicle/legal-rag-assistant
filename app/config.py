import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag"))

    # Plain OpenAI is used unless an Azure OpenAI endpoint is configured.
    openai_api_key: str | None = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    azure_endpoint: str | None = field(default_factory=lambda: _env("AZURE_OPENAI_ENDPOINT"))
    azure_api_key: str | None = field(default_factory=lambda: _env("AZURE_OPENAI_API_KEY"))
    azure_api_version: str = field(default_factory=lambda: _env("AZURE_OPENAI_API_VERSION", "2024-10-21"))

    # With Azure these are deployment names rather than model names.
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "text-embedding-3-small"))
    embedding_dim: int = field(default_factory=lambda: int(_env("EMBEDDING_DIM", "1536")))
    chat_model: str = field(default_factory=lambda: _env("CHAT_MODEL", "gpt-4o-mini"))

    chunk_size: int = field(default_factory=lambda: int(_env("CHUNK_SIZE", "800")))
    chunk_overlap: int = field(default_factory=lambda: int(_env("CHUNK_OVERLAP", "150")))
    top_k: int = field(default_factory=lambda: int(_env("TOP_K", "5")))


settings = Settings()
