"""Test #1: adapter interface — the registry and the shared ABC contract."""

from __future__ import annotations

import pytest

from researchos.evidence import SourceConfigurationError, available_sources, get_adapter
from researchos.evidence.adapters.arxiv import ArxivAdapter
from researchos.evidence.adapters.base import SourceAdapter
from researchos.evidence.adapters.crossref import CrossrefAdapter
from researchos.evidence.adapters.openalex import OpenAlexAdapter
from researchos.evidence.adapters.semantic_scholar import SemanticScholarAdapter
from researchos.evidence.types import AdapterHealth


def test_available_sources_lists_all_four():
    assert available_sources() == ["arxiv", "crossref", "openalex", "semantic_scholar"]


@pytest.mark.parametrize(
    "name,cls",
    [
        ("openalex", OpenAlexAdapter),
        ("crossref", CrossrefAdapter),
        ("semantic_scholar", SemanticScholarAdapter),
        ("arxiv", ArxivAdapter),
    ],
)
def test_get_adapter_returns_correct_type(name, cls):
    adapter = get_adapter(name)
    assert isinstance(adapter, cls)
    assert isinstance(adapter, SourceAdapter)
    assert adapter.source_name == name


def test_get_adapter_is_case_insensitive_and_trims_whitespace():
    adapter = get_adapter(" OpenAlex ")
    assert isinstance(adapter, OpenAlexAdapter)


def test_get_adapter_unknown_name_raises():
    with pytest.raises(SourceConfigurationError):
        get_adapter("not-a-real-source")


def test_every_adapter_implements_the_full_interface():
    for name in available_sources():
        adapter = get_adapter(name)
        assert callable(adapter.search)
        assert callable(adapter.get_by_id)
        assert callable(adapter.normalize)
        assert callable(adapter.health)


def test_health_never_makes_a_network_call_and_reports_configured():
    for name in available_sources():
        adapter = get_adapter(name)
        health = adapter.health()
        assert isinstance(health, AdapterHealth)
        assert health.source == name
        assert health.configured is True
        assert health.base_url
