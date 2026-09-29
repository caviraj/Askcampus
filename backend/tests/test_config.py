"""Configuration parsing, defaults and fail-fast behaviour."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.fakes import TEST_SUPABASE_URL


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "supabase_url": TEST_SUPABASE_URL,
        "supabase_service_role_key": "test-service-role-key",
        "gemini_api_key": "test-gemini-api-key",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_cors_origins_parsed_from_comma_separated_string() -> None:
    settings = _settings(cors_origins="https://a.example, https://b.example")
    assert settings.cors_origins == ["https://a.example", "https://b.example"]


def test_cors_origins_accepts_an_already_split_list() -> None:
    settings = _settings(cors_origins=["https://a.example"])
    assert settings.cors_origins == ["https://a.example"]


def test_cors_origins_drops_empty_entries() -> None:
    settings = _settings(cors_origins="https://a.example,,")
    assert settings.cors_origins == ["https://a.example"]


def test_retrieval_constants_default_to_the_spec_values() -> None:
    settings = _settings()
    assert settings.top_k == 5
    assert settings.similarity_threshold == 0.55
    assert settings.max_upload_mb == 20
    assert settings.embedding_dimensions == 768
    # Both model names differ from ARCHITECTURE.md section 2, which named a
    # retired embedding model and a generation model Google no longer offers to
    # new projects. See the comments in app/config.py.
    assert settings.llm_model == "gemini-3.8-flash"
    assert settings.embedding_model == "gemini-embedding-001"


def test_chunk_defaults_match_the_spec() -> None:
    settings = _settings()
    assert settings.chunk_target_tokens == 300
    assert settings.chunk_max_tokens == 500
    assert settings.chunk_overlap_tokens == 50


def test_an_unusable_chunk_budget_fails_fast() -> None:
    """An overlap at or above the target would make the chunker never terminate."""
    with pytest.raises(ValidationError):
        _settings(chunk_target_tokens=300, chunk_overlap_tokens=300)


def test_a_list_limit_above_the_maximum_fails_fast() -> None:
    with pytest.raises(ValidationError):
        _settings(document_list_default_limit=500, document_list_max_limit=100)


def test_top_k_is_bounded() -> None:
    with pytest.raises(ValidationError):
        _settings(top_k=0)


def test_missing_supabase_url_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_secrets_do_not_appear_in_repr_or_str() -> None:
    settings = _settings(supabase_service_role_key="super-secret-value")
    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings)
    # The real value is still reachable where it is actually needed.
    assert settings.supabase_service_role_key.get_secret_value() == "super-secret-value"


def test_trailing_slash_is_stripped_and_urls_derive_cleanly() -> None:
    settings = _settings(supabase_url="https://test-project.supabase.co/")
    assert settings.supabase_url == "https://test-project.supabase.co"
    assert settings.jwks_url == ("https://test-project.supabase.co/auth/v1/.well-known/jwks.json")
    assert settings.jwt_issuer == "https://test-project.supabase.co/auth/v1"


def test_missing_gemini_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Required since Phase 2. Ingestion cannot run without it, and failing at
    startup beats failing inside a background task where the exception is
    swallowed and the document is left stuck in `processing`."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            supabase_url=TEST_SUPABASE_URL,
            supabase_service_role_key="test-service-role-key",
        )


def test_the_gemini_key_does_not_appear_in_repr_or_str() -> None:
    settings = _settings(gemini_api_key="super-secret-gemini-value")
    assert "super-secret-gemini-value" not in repr(settings)
    assert "super-secret-gemini-value" not in str(settings)
    assert settings.gemini_api_key.get_secret_value() == "super-secret-gemini-value"


def test_cors_origins_default_is_local_dev_not_a_wildcard() -> None:
    origins = _settings().cors_origins
    assert "*" not in origins
    assert origins == ["http://localhost:5173"]
