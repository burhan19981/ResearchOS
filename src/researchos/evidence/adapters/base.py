"""Common interface every source adapter implements.

```
search()      -> SearchResult              (a page of NormalizedRecord)
get_by_id()   -> Optional[NormalizedRecord] (None on a genuine 404)
normalize()   -> NormalizedRecord           (raw source dict -> normalized shape)
health()      -> AdapterHealth              (configured?, base URL — no network call)
```

Adapters share their HTTP/cache/retry wiring through this base class's
`_get_json`/`_get_text` protected helpers so that behavior (timeout,
retry, rate-limit handling, caching) is implemented exactly once and is
identical across all four sources — only the URL/params/response
*shape* differs per adapter.
"""

from __future__ import annotations

import json as json_module
from abc import ABC, abstractmethod
from typing import Any, Optional

from .._http import Transport, default_transport, fetch
from ..cache import EvidenceCache, build_cache, make_cache_key
from ..config import CacheConfig, SourceConfig, load_cache_config
from ..errors import SourceNotFoundError, SourceResponseError
from ..types import AdapterHealth, NormalizedRecord, SearchFilters, SearchResult


class SourceAdapter(ABC):
    def __init__(
        self,
        config: SourceConfig,
        *,
        transport: Optional[Transport] = None,
        cache: Optional[EvidenceCache] = None,
        cache_config: Optional[CacheConfig] = None,
    ) -> None:
        self._config = config
        self._transport = transport or default_transport()
        resolved_cache_config = cache_config or load_cache_config()
        self._cache = cache if cache is not None else build_cache(resolved_cache_config)
        self._cache_ttl = resolved_cache_config.ttl_seconds

    @property
    @abstractmethod
    def source_name(self) -> str: ...

    @abstractmethod
    def search(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        *,
        page: int = 1,
        page_size: int = 25,
        cursor: Optional[str] = None,
    ) -> SearchResult: ...

    @abstractmethod
    def get_by_id(self, source_record_id: str) -> Optional[NormalizedRecord]: ...

    @abstractmethod
    def normalize(self, raw: dict[str, Any]) -> NormalizedRecord: ...

    def health(self) -> AdapterHealth:
        """No network call — just reports whether configuration resolved."""
        configured = bool(self._config.base_url)
        return AdapterHealth(source=self.source_name, configured=configured, base_url=self._config.base_url)

    # -- shared HTTP + cache plumbing -------------------------------------

    def _get_json(
        self, url: str, *, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None,
        operation: str,
    ) -> dict[str, Any]:
        cache_key = make_cache_key(self.source_name, operation, params or {})
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        response = fetch(self._transport, self._config, url=url, params=params, headers=headers)
        if response.status == 404:
            raise SourceNotFoundError(f"{self.source_name}: no record found ({url}).")
        try:
            data = json_module.loads(response.text())
        except json_module.JSONDecodeError as exc:
            raise SourceResponseError(f"{self.source_name}: response was not valid JSON.") from exc
        if not isinstance(data, dict):
            raise SourceResponseError(f"{self.source_name}: expected a JSON object, got {type(data).__name__}.")

        self._cache.set(cache_key, data, self._cache_ttl)
        return data

    def _get_text(
        self, url: str, *, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None,
        operation: str,
    ) -> str:
        cache_key = make_cache_key(self.source_name, operation, params or {})
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        response = fetch(self._transport, self._config, url=url, params=params, headers=headers)
        if response.status == 404:
            raise SourceNotFoundError(f"{self.source_name}: no record found ({url}).")
        text = response.text()
        self._cache.set(cache_key, text, self._cache_ttl)
        return text
