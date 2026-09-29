"""Application configuration.

Every tunable constant in the project is defined here and nowhere else, as
AGENTS.md section 7 requires. Later phases import these rather than hardcoding.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Resolved from this file rather than the current working directory, so pytest
# run from the repo root finds the same .env as uvicorn run from backend/.
_BACKEND_DIR = Path(__file__).resolve().parents[1]


def _split_csv(value: object) -> object:
    """Turn "a.com,b.com" into ["a.com", "b.com"].

    Needed because pydantic-settings JSON-decodes complex fields in the settings
    source, before any field_validator runs, so a comma-separated string would
    otherwise raise a SettingsError the validator never sees.
    """
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


CommaSeparated = Annotated[list[str], NoDecode, BeforeValidator(_split_csv)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Required. A missing value raises ValidationError at startup with the field
    # named, rather than surfacing as a 500 on the first request.
    supabase_url: str
    supabase_service_role_key: SecretStr

    # Optional in Phase 1: no provider is implemented yet, and requiring it would
    # block offline verification. Phase 2 makes it required.
    gemini_api_key: SecretStr | None = None
    llm_model: str = "gemini-2.5-flash"
    embedding_model: str = "text-embedding-004"
    # Must match vector(768) in the chunks table.
    embedding_dimensions: int = 768

    # Retrieval tuning. Tuned against the eval set in Phase 6.
    similarity_threshold: float = Field(default=0.55, ge=-1.0, le=1.0)
    top_k: int = Field(default=5, ge=1, le=20)
    max_upload_mb: int = Field(default=20, gt=0)

    # Never ["*"]: a wildcard origin would let any site call the API.
    cors_origins: CommaSeparated = ["http://localhost:5173"]

    # Admin auth. Tokens are verified against the JWKS endpoint derived from
    # supabase_url; there is no shared secret, see app/services/auth.py.
    jwt_audience: str = "authenticated"
    jwt_leeway_seconds: int = Field(default=10, ge=0)
    jwks_cache_seconds: int = Field(default=300, gt=0)

    environment: Literal["local", "dev", "prod"] = "local"
    log_level: str = "INFO"

    @field_validator("supabase_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url}/auth/v1"


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is read once per process."""
    return Settings()
