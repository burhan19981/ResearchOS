"""Configuration for evidence/literature source adapters.

Every setting is read from an environment variable (optionally
populated from a local `.env` file — never committed); nothing is
hard-coded, and no adapter requires a secret to function at all (a
"contact email" is a courtesy identifier some sources ask polite API
consumers to supply for higher rate limits, not a credential).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# src/researchos/evidence/config.py -> parents[3] is the repository root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"

DEFAULT_OPENALEX_API_URL = "https://api.openalex.org"
DEFAULT_CROSSREF_API_URL = "https://api.crossref.org"
DEFAULT_SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1"
DEFAULT_ARXIV_API_URL = "https://export.arxiv.org/api/query"

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_RETRIES = 3

DEFAULT_CACHE_DIR = _PROJECT_ROOT / "data" / "cache" / "evidence"
DEFAULT_CACHE_TTL_SECONDS = 86_400  # 24 hours — bibliographic metadata changes slowly.


def load_dotenv_if_present() -> None:
    load_dotenv(dotenv_path=_ENV_FILE, override=False)


@dataclass(frozen=True)
class SourceConfig:
    source: str
    base_url: str
    timeout: float
    max_retries: int
    contact_email: Optional[str] = None
    api_key: Optional[str] = None


@dataclass(frozen=True)
class CacheConfig:
    enabled: bool
    directory: Path
    ttl_seconds: int


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


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _shared_timeout() -> float:
    return _get_float_env("RESEARCHOS_EVIDENCE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)


def _shared_max_retries() -> int:
    return _get_int_env("RESEARCHOS_EVIDENCE_MAX_RETRIES", DEFAULT_MAX_RETRIES)


def load_openalex_config() -> SourceConfig:
    load_dotenv_if_present()
    return SourceConfig(
        source="openalex",
        base_url=os.environ.get("OPENALEX_API_URL") or DEFAULT_OPENALEX_API_URL,
        timeout=_shared_timeout(),
        max_retries=_shared_max_retries(),
        contact_email=os.environ.get("OPENALEX_CONTACT_EMAIL") or None,
    )


def load_crossref_config() -> SourceConfig:
    load_dotenv_if_present()
    return SourceConfig(
        source="crossref",
        base_url=os.environ.get("CROSSREF_API_URL") or DEFAULT_CROSSREF_API_URL,
        timeout=_shared_timeout(),
        max_retries=_shared_max_retries(),
        contact_email=os.environ.get("CROSSREF_CONTACT_EMAIL") or None,
    )


def load_semantic_scholar_config() -> SourceConfig:
    load_dotenv_if_present()
    return SourceConfig(
        source="semantic_scholar",
        base_url=os.environ.get("SEMANTIC_SCHOLAR_API_URL") or DEFAULT_SEMANTIC_SCHOLAR_API_URL,
        timeout=_shared_timeout(),
        max_retries=_shared_max_retries(),
        api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY") or None,
    )


def load_arxiv_config() -> SourceConfig:
    load_dotenv_if_present()
    return SourceConfig(
        source="arxiv",
        base_url=os.environ.get("ARXIV_API_URL") or DEFAULT_ARXIV_API_URL,
        timeout=_shared_timeout(),
        max_retries=_shared_max_retries(),
    )


def load_cache_config() -> CacheConfig:
    load_dotenv_if_present()
    directory = os.environ.get("RESEARCHOS_EVIDENCE_CACHE_DIR")
    return CacheConfig(
        enabled=_get_bool_env("RESEARCHOS_EVIDENCE_CACHE_ENABLED", True),
        directory=Path(directory) if directory else DEFAULT_CACHE_DIR,
        ttl_seconds=_get_int_env("RESEARCHOS_EVIDENCE_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS),
    )
