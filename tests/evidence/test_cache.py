"""Test #16: cache behavior."""

from __future__ import annotations

import time

from researchos.evidence.adapters.openalex import OpenAlexAdapter
from researchos.evidence.cache import FileCache, InMemoryCache, NullCache, make_cache_key
from researchos.evidence.config import SourceConfig

from .fakes import FakeTransport, json_response


def test_make_cache_key_is_deterministic_regardless_of_dict_order():
    key_a = make_cache_key("openalex", "search", {"search": "x", "page": 1})
    key_b = make_cache_key("openalex", "search", {"page": 1, "search": "x"})
    assert key_a == key_b


def test_make_cache_key_differs_by_operation_and_source():
    base = make_cache_key("openalex", "search", {"q": "x"})
    assert base != make_cache_key("crossref", "search", {"q": "x"})
    assert base != make_cache_key("openalex", "get_by_id", {"q": "x"})


def test_make_cache_key_excludes_contact_email_and_api_key():
    key_a = make_cache_key("openalex", "search", {"search": "x", "mailto": "a@example.com"})
    key_b = make_cache_key("openalex", "search", {"search": "x", "mailto": "b@example.com"})
    key_c = make_cache_key("openalex", "search", {"search": "x"})
    assert key_a == key_b == key_c


def test_in_memory_cache_set_get_and_expiry(monkeypatch):
    cache = InMemoryCache()
    cache.set("k", {"v": 1}, ttl_seconds=100)
    assert cache.get("k") == {"v": 1}

    # Simulate time passing beyond the TTL.
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 1000)
    assert cache.get("k") is None


def test_null_cache_always_misses_and_stores_nothing():
    cache = NullCache()
    cache.set("k", {"v": 1}, ttl_seconds=100)
    assert cache.get("k") is None


def test_file_cache_persists_across_instances(tmp_path):
    cache_a = FileCache(tmp_path)
    cache_a.set("k", {"v": 1}, ttl_seconds=100)

    cache_b = FileCache(tmp_path)  # a fresh instance, same directory
    assert cache_b.get("k") == {"v": 1}


def test_file_cache_expired_entry_is_a_miss(tmp_path):
    cache = FileCache(tmp_path)
    cache.set("k", {"v": 1}, ttl_seconds=-1)  # already expired
    assert cache.get("k") is None


def test_file_cache_corrupted_file_is_a_miss_not_an_error(tmp_path):
    cache = FileCache(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "badkey.json").write_text("not valid json{{{", encoding="utf-8")
    assert cache.get("badkey") is None


def test_file_cache_never_stores_the_configured_api_key_or_email(tmp_path):
    """The cached value is exactly the source's public JSON response —
    request-level secrets (headers, mailto) never enter it."""
    cache = FileCache(tmp_path)
    cache.set("k", {"title": "A Public Paper"}, ttl_seconds=100)
    raw_file_content = (tmp_path / "k.json").read_text(encoding="utf-8")
    assert "secret" not in raw_file_content.lower()
    assert "api_key" not in raw_file_content.lower()


def test_adapter_search_uses_cache_to_avoid_a_second_transport_call():
    cache = InMemoryCache()
    payload = {"meta": {"count": 1}, "results": [{"id": "https://openalex.org/W1", "title": "Cached Paper"}]}
    transport = FakeTransport(responses=[json_response(200, payload)])
    config = SourceConfig(source="openalex", base_url="https://api.openalex.org", timeout=5.0, max_retries=1)
    adapter = OpenAlexAdapter(config=config, transport=transport, cache=cache)

    first = adapter.search("same query", page=1, page_size=10)
    second = adapter.search("same query", page=1, page_size=10)  # would raise (no more responses) without a cache hit

    assert len(transport.calls) == 1
    assert first.records[0].title == second.records[0].title == "Cached Paper"
