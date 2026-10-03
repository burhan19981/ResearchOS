"""Environment-based configuration loading for LLM providers.

Reads credentials and model names from environment variables, optionally
populated from a local `.env` file (never committed — see `.gitignore`)
via `python-dotenv`. No secret value is ever logged or included in an
exception message by this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# src/researchos/llm/config.py -> parents[3] is the repository root.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

# Documented, overridable defaults — see docs/PHASE2_LLM_PROVIDERS.md for
# rationale. Override via ANTHROPIC_MODEL / OPENAI_MODEL; verify current
# availability and pricing with the provider before real use.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 2


def load_dotenv_if_present() -> None:
    """Load variables from a local `.env` file, if one exists.

    Never overrides a variable already set in the real process
    environment, and never raises if the file is absent.
    """
    load_dotenv(dotenv_path=_ENV_FILE, override=False)


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    api_key: Optional[str]
    model: str
    timeout: float
    max_retries: int

    @property
    def is_configured(self) -> bool:
        """Whether required credentials are present. Never exposes the key itself."""
        return bool(self.api_key)


def _get_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_anthropic_config() -> ProviderConfig:
    load_dotenv_if_present()
    return ProviderConfig(
        provider="anthropic",
        api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        model=os.environ.get("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL,
        timeout=_get_float_env("ANTHROPIC_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        max_retries=_get_int_env("ANTHROPIC_MAX_RETRIES", DEFAULT_MAX_RETRIES),
    )


def load_openai_config() -> ProviderConfig:
    load_dotenv_if_present()
    return ProviderConfig(
        provider="openai",
        api_key=os.environ.get("OPENAI_API_KEY") or None,
        model=os.environ.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
        timeout=_get_float_env("OPENAI_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        max_retries=_get_int_env("OPENAI_MAX_RETRIES", DEFAULT_MAX_RETRIES),
    )
