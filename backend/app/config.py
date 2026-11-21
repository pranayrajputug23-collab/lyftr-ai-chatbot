"""Environment-backed application settings."""

from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:////data/app.db"
    llm_api_keys: tuple[str, ...] = field(default_factory=tuple)
    llm_model: str = "gpt-4o-mini"
    llm_api_base: str | None = None
    llm_provider: str = "openai"
    allowed_origins: tuple[str, ...] = ("http://localhost:3000",)
    enable_failure_simulation: bool = False
    cache_enabled: bool = True
    cache_type: str = "local"

    @classmethod
    def from_env(cls) -> "Settings":
        keys = tuple(value.strip() for value in os.getenv("LLM_API_KEYS", "").split(",") if value.strip())
        origins = tuple(value.strip() for value in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if value.strip())
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:////data/app.db"),
            llm_api_keys=keys,
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            llm_api_base=os.getenv("LLM_API_BASE") or None,
            llm_provider=os.getenv("LLM_PROVIDER", "openai"),
            allowed_origins=origins,
            enable_failure_simulation=os.getenv("ENABLE_FAILURE_SIMULATION", "false").lower() in {"1", "true", "yes", "on"},
            cache_enabled=os.getenv("CACHE_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
            cache_type=os.getenv("LITELLM_CACHE_TYPE", "local"),
        )


def sqlite_path(database_url: str) -> str:
    """Convert a SQLite URL or filesystem path to a sqlite3-compatible path."""
    if database_url.startswith("sqlite:////"):
        return database_url[len("sqlite:///"):]
    if database_url.startswith("sqlite:///"):
        return database_url[len("sqlite:///"):]
    if database_url.startswith("sqlite://"):
        return database_url[len("sqlite://"):]
    if "://" in database_url:
        raise ValueError("Only SQLite database URLs are supported")
    return database_url
