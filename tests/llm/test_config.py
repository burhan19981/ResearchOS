from researchos.llm.config import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_MODEL,
    load_anthropic_config,
    load_openai_config,
)


def test_anthropic_config_defaults_when_unset():
    config = load_anthropic_config()
    assert config.provider == "anthropic"
    assert config.api_key is None
    assert config.model == DEFAULT_ANTHROPIC_MODEL
    assert config.is_configured is False


def test_anthropic_config_reads_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-custom-model")
    config = load_anthropic_config()
    assert config.api_key == "sk-ant-fake-test-key"
    assert config.model == "claude-custom-model"
    assert config.is_configured is True


def test_openai_config_defaults_when_unset():
    config = load_openai_config()
    assert config.provider == "openai"
    assert config.api_key is None
    assert config.model == DEFAULT_OPENAI_MODEL
    assert config.is_configured is False


def test_openai_config_reads_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-custom")
    config = load_openai_config()
    assert config.api_key == "sk-fake-test-key"
    assert config.model == "gpt-custom"
    assert config.is_configured is True


def test_invalid_numeric_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_TIMEOUT_SECONDS", "not-a-number")
    config = load_anthropic_config()
    assert config.timeout == 60.0


def test_blank_api_key_env_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    config = load_openai_config()
    assert config.api_key is None
    assert config.is_configured is False
