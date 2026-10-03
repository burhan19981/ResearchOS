"""Shared test fixtures for the LLM provider layer.

Every test runs with a clean environment and with `.env` loading
disabled, so results never depend on real developer credentials that
might exist on disk or in the shell.
"""

from __future__ import annotations

import pytest

_LLM_ENV_VARS = [
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_TIMEOUT_SECONDS",
    "ANTHROPIC_MAX_RETRIES",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_TIMEOUT_SECONDS",
    "OPENAI_MAX_RETRIES",
]


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch):
    for name in _LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture(autouse=True)
def no_dotenv_loading(monkeypatch):
    # Prevent a real local .env file (if a developer has created one)
    # from leaking credentials into test runs.
    monkeypatch.setattr("researchos.llm.config.load_dotenv", lambda *a, **k: None)
