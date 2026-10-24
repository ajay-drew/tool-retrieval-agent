import pytest

from atlas.config import Settings
from atlas.llm import MissingKeyError, build_chat_model, is_retryable_model_error


def test_defaults_match_architecture(monkeypatch):
    for name in ("LLM_API_KEY", "LANGSMITH_API_KEY", "ATLAS_K", "ATLAS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.atlas_model == "gemini-3.5-flash"
    assert settings.llm_base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert settings.atlas_k == 8
    assert settings.langsmith_project == "atlas"
    assert settings.tracing_enabled is False


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("ATLAS_K", "5")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    settings = Settings(_env_file=None)
    assert settings.atlas_k == 5
    assert settings.tracing_enabled is True


def test_blank_keys_count_as_unset(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LANGSMITH_API_KEY", "  ")
    settings = Settings(_env_file=None)
    assert settings.llm_api_key is None
    assert settings.tracing_enabled is False


def test_missing_llm_key_is_explicit(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="LLM_API_KEY"):
        build_chat_model(Settings(_env_file=None))


def test_default_provider_is_native_gemini(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    model = build_chat_model(Settings(_env_file=None))
    assert type(model).__name__ == "ChatGoogleGenerativeAI"
    assert model.model == "gemini-3.5-flash"
    assert model.temperature == 0


def test_openai_compatible_provider(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("ATLAS_LLM_PROVIDER", "openai")
    model = build_chat_model(Settings(_env_file=None))
    assert model.openai_api_base == "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_daily_quota_is_not_retried_but_per_minute_is():
    daily = RuntimeError("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    minute = RuntimeError("429 RESOURCE_EXHAUSTED GenerateContentInputTokensPerModelPerMinute")
    assert not is_retryable_model_error(daily)
    assert is_retryable_model_error(minute)
    assert not is_retryable_model_error(ValueError("bad input"))
