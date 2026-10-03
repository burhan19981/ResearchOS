"""A small, deterministic local cache for raw source responses.

Caches the *raw* response (JSON dict or XML text) a source returned,
keyed deterministically by `(source, operation, params)` — never the
normalized `NormalizedRecord`, so a future change to normalization
logic can't be served stale by the cache. Never caches secrets: request
params known to carry a contact identifier or API key
(`mailto`, `api_key`, `x-api-key`) are excluded from the key, and
nothing about credentials is ever part of a cached value either (cached
values are exactly the source's own public bibliographic JSON/XML).

Two backends: `FileCache` (default — persists across process runs,
under `data/cache/evidence/`, gitignored) and `InMemoryCache` (for
tests, or when persistence isn't wanted). `NullCache` always misses,
for when caching is disabled entirely.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional, Protocol

from .config import CacheConfig

_EXCLUDED_PARAM_KEYS = {"mailto", "api_key", "apikey", "x-api-key", "key"}


def make_cache_key(source: str, operation: str, params: dict[str, Any]) -> str:
    """A deterministic cache key for one (source, operation, params) call.

    Excludes contact-email/API-key-shaped params so the key never
    depends on which contact identifier happens to be configured, and
    never embeds a credential even indirectly.
    """
    filtered = {k: v for k, v in sorted(params.items()) if k.lower() not in _EXCLUDED_PARAM_KEYS and v is not None}
    canonical = json.dumps({"source": source, "operation": operation, "params": filtered}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EvidenceCache(Protocol):
    def get(self, key: str) -> Optional[Any]: ...

    def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...


class NullCache:
    """Always misses, stores nothing. Used when caching is disabled."""

    def get(self, key: str) -> Optional[Any]:
        return None

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        return None


class InMemoryCache:
    """Process-local cache — gone as soon as the process exits."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._store[key] = (time.time() + ttl_seconds, value)


class FileCache:
    """Persists cached values as JSON files under a directory.

    A corrupted or unreadable cache file is treated as a cache miss
    (never raises) — the cache is purely a performance optimization,
    never a source of truth.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _path(self, key: str) -> Path:
        return self._directory / f"{key}.json"

    def get(self, key: str) -> Optional[Any]:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict) or "expires_at" not in payload or "value" not in payload:
            return None
        if time.time() > payload["expires_at"]:
            return None
        return payload["value"]

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        payload = {"expires_at": time.time() + ttl_seconds, "value": value}
        try:
            self._path(key).write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass  # caching is best-effort; a write failure must never break a search


def build_cache(config: CacheConfig) -> EvidenceCache:
    if not config.enabled:
        return NullCache()
    return FileCache(config.directory)
