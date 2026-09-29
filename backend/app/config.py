"""Application configuration.

Every tunable constant in the project is defined here and nowhere else, as
AGENTS.md section 7 requires. Later phases import these rather than hardcoding.

The line between here and a module constant in a service: a value belongs here
if changing it is an operational decision (how many chunks to embed at once, how
big an upload may be). Pure algorithm details with no operational meaning -- the
PDF heading font ratio, the tokenizer's characters-per-token divisors -- stay
next to the code that uses them, because exposing them would be configuration
theatre.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BeforeValidator,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Resolved from this file rather than the current working directory, so pytest
# run from the repo root finds the same .env as uvicorn run from backend/.
_BACKEND_DIR = Path(__file__).resolve().parents[1]

_MEGABYTE = 1024 * 1024


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

    # Required from Phase 2: ingestion cannot run without it. Failing at startup
    # is far better than failing inside a background task, where the exception is
    # swallowed by the web server and the document is left stuck in `processing`.
    gemini_api_key: SecretStr

    # ARCHITECTURE.md section 2 named gemini-2.5-flash, which Google now
    # restricts to projects that used it before a cutoff; new projects are
    # pointed at the 3.x line. Overridable, so a key that still has 2.5 access
    # can use it.
    llm_model: str = "gemini-3.8-flash"

    # ARCHITECTURE.md section 2 named text-embedding-004, which Google retired on
    # 2026-01-14. gemini-embedding-001 is the current model; both support
    # Matryoshka truncation, so 768 is a supported width rather than a mismatch.
    embedding_model: str = "gemini-embedding-001"

    # Must match vector(768) in the chunks table. Asserted against the schema at
    # startup -- without it, a width mismatch surfaces as a pgvector cast error
    # that never mentions dimensions.
    embedding_dimensions: int = 768

    # Asymmetric retrieval: documents are embedded as RETRIEVAL_DOCUMENT and
    # questions as RETRIEVAL_QUERY. Using the wrong one on either side degrades
    # recall silently, with no error to catch -- which is why they are two
    # settings rather than one that a caller could pass wrongly.
    embedding_task_type: str = "RETRIEVAL_DOCUMENT"
    query_embedding_task_type: str = "RETRIEVAL_QUERY"

    # Retrieval tuning. `eval/run_eval.py --sweep` reports the threshold that
    # meets the section 9 targets, but only for whichever provider it ran on, and
    # the two providers do not share a scale: the offline lexical stand-in puts
    # that number at 0.25, which is not 0.25 here.
    #
    # The Gemini run is the one that counts, and it was run against the real
    # embedder. It did not move this value, because on this corpus the threshold
    # is not what binds: at 0.55 every out-of-scope question was refused and the
    # answer-rate target was met, while the one answer that cited a document that
    # does not hold its fact sat at 0.600 -- raising the threshold past it would
    # have to pass 0.646 and 0.665, and would cost two correct answers to remove
    # one wrong one. That failure is a classification defect, not a threshold
    # one; see `app/services/classifier.py`. ARCHITECTURE.md names 0.55 as the
    # starting point and nothing measured since has argued for leaving it.
    #
    # A full sweep costs roughly 500 generation calls, and the generation
    # endpoint was returning 503s throughout the run that measured the above, so
    # the sweep is deferred rather than done. Re-run it when that endpoint is
    # healthy: `python eval/run_eval.py --provider gemini --sweep`.
    similarity_threshold: float = Field(default=0.55, ge=-1.0, le=1.0)
    top_k: int = Field(default=5, ge=1, le=20)
    max_upload_mb: int = Field(default=20, gt=0)

    # Chat. ARCHITECTURE.md section 5.2 fixes the history window at four turns.
    chat_history_max_turns: int = Field(default=4, ge=0, le=20)
    chat_question_max_chars: int = Field(default=1000, gt=0)
    chat_history_max_chars: int = Field(default=1000, gt=0)
    # ARCHITECTURE.md section 9 suggests "for example 20 per minute". Counted per
    # IP and per session, in the process -- a single-instance assumption, the same
    # one the startup reaper documents.
    chat_rate_limit_enabled: bool = True
    chat_rate_limit_per_minute: int = Field(default=20, gt=0)

    # Chunking. Target, max and overlap come from ARCHITECTURE.md section 8.
    chunk_target_tokens: int = Field(default=300, gt=0)
    chunk_max_tokens: int = Field(default=500, gt=0)
    chunk_overlap_tokens: int = Field(default=50, ge=0)
    # Not from the spec: a floor that stops two-word fragments reaching the index.
    # A trailing section shorter than this is folded into the previous chunk.
    chunk_min_tokens: int = Field(default=40, ge=0)

    # Embedding.
    embed_batch_size: int = Field(default=50, gt=0)
    embedding_max_retries: int = Field(default=3, ge=0)
    retry_backoff_seconds: float = Field(default=0.5, ge=0.0)
    # AGENTS.md section 10 names a 30 s provider timeout as a handled edge case.
    provider_timeout_seconds: float = Field(default=30.0, gt=0)
    embedding_cache_enabled: bool = True

    # Storage. The bucket is created by migration 0003.
    storage_bucket: str = "documents"
    storage_timeout_seconds: float = Field(default=60.0, gt=0)

    # Extraction.
    allowed_upload_extensions: CommaSeparated = ["pdf", "docx", "txt"]
    max_document_pages: int = Field(default=300, gt=0)
    # Zip-bomb guard for DOCX: a 20 MB archive can expand to gigabytes.
    max_archive_uncompressed_mb: int = Field(default=100, gt=0)
    # A scanned PDF has no text layer; most pages under this many characters
    # means the document is flagged low-yield rather than failed.
    min_chars_per_page: int = Field(default=100, ge=0)
    low_yield_page_ratio: float = Field(default=0.5, ge=0.0, le=1.0)
    text_preview_chars: int = Field(default=500, gt=0)

    # Admin API. The max bounds what a caller can ask for in one page.
    document_list_default_limit: int = Field(default=20, gt=0)
    document_list_max_limit: int = Field(default=100, gt=0)

    # Query history, the unanswered queue and the FAQ view.
    admin_list_default_limit: int = Field(default=20, gt=0)
    admin_list_max_limit: int = Field(default=100, gt=0)
    stats_window_days: int = Field(default=7, gt=0)
    faq_max_items_per_category: int = Field(default=5, gt=0)
    # How many unanswered groups the dashboard previews. DESIGN_SYSTEM.md
    # section 8 asks for a preview, not the queue: the queue has its own screen.
    stats_preview_limit: int = Field(default=5, gt=0)
    # PostgREST exposes one statement per request and has no GROUP BY, so the
    # grouped views (the unanswered queue, the FAQ list, the category chart) are
    # aggregated in Python over a bounded window of rows. This is that bound. A
    # response that hits it sets `truncated`, so a partial count is reported as
    # partial rather than presented as a total. A paging or `count` query would
    # not help -- the grouping is what needs the rows.
    admin_aggregate_row_limit: int = Field(default=5000, gt=0)

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

    @field_validator("allowed_upload_extensions")
    @classmethod
    def _normalise_extensions(cls, value: list[str]) -> list[str]:
        """Accept "pdf", ".PDF", " pdf " and store "pdf"."""
        cleaned = [item.strip().lstrip(".").lower() for item in value]
        extensions = [item for item in cleaned if item]
        if not extensions:
            raise ValueError("allowed_upload_extensions must not be empty")
        return extensions

    @field_validator("storage_bucket")
    @classmethod
    def _reject_empty_bucket(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("storage_bucket must not be empty")
        return value.strip()

    @model_validator(mode="after")
    def _check_chunk_budget(self) -> Settings:
        """Fail at startup on a chunk configuration the chunker cannot honour.

        An overlap at or above the target would make the chunker emit the same
        text forever, so it is worth catching here rather than as a hung request.
        """
        if not self.chunk_min_tokens < self.chunk_target_tokens <= self.chunk_max_tokens:
            raise ValueError(
                "chunk sizes must satisfy chunk_min_tokens < chunk_target_tokens "
                "<= chunk_max_tokens"
            )
        if self.chunk_overlap_tokens >= self.chunk_target_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_target_tokens")
        if self.document_list_default_limit > self.document_list_max_limit:
            raise ValueError("document_list_default_limit must not exceed document_list_max_limit")
        return self

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url}/auth/v1"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * _MEGABYTE

    @property
    def max_archive_uncompressed_bytes(self) -> int:
        return self.max_archive_uncompressed_mb * _MEGABYTE


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is read once per process."""
    return Settings()
