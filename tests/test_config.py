import pytest

from atlas.config import Settings
from atlas.llm import MissingKeyError, build_chat_model


def test_defaults_match_architecture(monkeypatch):
    for name in ("OPENROUTER_API_KEY", "LANGSMITH_API_KEY", "ATLAS_K", "ATLAS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.atlas_model == "deepseek/deepseek-v4-flash"
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
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
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("LANGSMITH_API_KEY", "  ")
    settings = Settings(_env_file=None)
    assert settings.openrouter_api_key is None
    assert settings.tracing_enabled is False


def test_missing_openrouter_key_is_explicit(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="OPENROUTER_API_KEY"):
        build_chat_model(Settings(_env_file=None))


def test_model_points_at_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    model = build_chat_model(Settings(_env_file=None))
    assert model.model_name == "deepseek/deepseek-v4-flash"
    assert model.openai_api_base == "https://openrouter.ai/api/v1"
    assert model.temperature == 0
