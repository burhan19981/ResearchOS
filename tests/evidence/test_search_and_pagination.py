"""Tests #6 (search query handling), #7 (pagination), #8 (filtering)."""

from __future__ import annotations

import pytest

from researchos.evidence.adapters.arxiv import ArxivAdapter
from researchos.evidence.adapters.crossref import CrossrefAdapter
from researchos.evidence.adapters.openalex import OpenAlexAdapter
from researchos.evidence.adapters.semantic_scholar import SemanticScholarAdapter
from researchos.evidence.cache import NullCache
from researchos.evidence.errors import UnsupportedFilterError
from researchos.evidence.types import SearchFilters

from .fakes import FakeTransport, json_response, text_response

# --- OpenAlex ---------------------------------------------------------


def _openalex_page(count_total: int, n_items: int):
    return {
        "meta": {"count": count_total},
        "results": [
            {"id": f"https://openalex.org/W{i}", "title": f"Paper {i}", "publication_year": 2020}
            for i in range(n_items)
        ],
    }


def test_openalex_search_sends_expected_params_and_parses_pagination():
    transport = FakeTransport(responses=[json_response(200, _openalex_page(count_total=50, n_items=10))])
    adapter = OpenAlexAdapter(transport=transport, cache=NullCache())

    result = adapter.search("graph neural networks", page=1, page_size=10)

    assert transport.calls[0]["params"]["search"] == "graph neural networks"
    assert transport.calls[0]["params"]["page"] == 1
    assert transport.calls[0]["params"]["per_page"] == 10
    assert len(result.records) == 10
    assert result.page_info.total == 50
    assert result.page_info.has_more is True
    assert result.page_info.page == 1


def test_openalex_last_page_has_more_false():
    transport = FakeTransport(responses=[json_response(200, _openalex_page(count_total=10, n_items=10))])
    adapter = OpenAlexAdapter(transport=transport, cache=NullCache())
    result = adapter.search("x", page=1, page_size=10)
    assert result.page_info.has_more is False


def test_openalex_filters_build_expected_filter_string():
    transport = FakeTransport(responses=[json_response(200, _openalex_page(0, 0))])
    adapter = OpenAlexAdapter(transport=transport, cache=NullCache())
    filters = SearchFilters(year_from=2020, year_to=2022, author="Jane Doe", venue="Nature", document_type="article")

    adapter.search("x", filters)

    filter_string = transport.calls[0]["params"]["filter"]
    assert "from_publication_date:2020-01-01" in filter_string
    assert "to_publication_date:2022-12-31" in filter_string
    assert "authorships.author.display_name.search:Jane Doe" in filter_string
    assert "primary_location.source.display_name.search:Nature" in filter_string
    assert "type:article" in filter_string


def test_openalex_missing_results_key_raises_response_error():
    from researchos.evidence.errors import SourceResponseError

    transport = FakeTransport(responses=[json_response(200, {"meta": {}})])
    adapter = OpenAlexAdapter(transport=transport, cache=NullCache())
    with pytest.raises(SourceResponseError):
        adapter.search("x")


# --- Crossref -----------------------------------------------------------


def _crossref_page(total: int, n_items: int):
    return {
        "message": {
            "total-results": total,
            "items": [{"DOI": f"10.1/{i}", "title": [f"Paper {i}"]} for i in range(n_items)],
        }
    }


def test_crossref_search_sends_offset_based_pagination():
    transport = FakeTransport(responses=[json_response(200, _crossref_page(30, 5))])
    adapter = CrossrefAdapter(transport=transport, cache=NullCache())

    result = adapter.search("quantum computing", page=2, page_size=5)

    assert transport.calls[0]["params"]["query"] == "quantum computing"
    assert transport.calls[0]["params"]["rows"] == 5
    assert transport.calls[0]["params"]["offset"] == 5  # (page 2 - 1) * page_size
    assert result.page_info.total == 30
    assert result.page_info.has_more is True


def test_crossref_filters_use_dedicated_query_params_and_filter_string():
    transport = FakeTransport(responses=[json_response(200, _crossref_page(0, 0))])
    adapter = CrossrefAdapter(transport=transport, cache=NullCache())
    filters = SearchFilters(author="Jane Doe", venue="Nature", year_from=2020, document_type="journal-article")

    adapter.search("x", filters)

    params = transport.calls[0]["params"]
    assert params["query.author"] == "Jane Doe"
    assert params["query.container-title"] == "Nature"
    assert "from-pub-date:2020-01-01" in params["filter"]
    assert "type:journal-article" in params["filter"]


# --- Semantic Scholar -----------------------------------------------------


def _s2_page(total: int, n_items: int, next_offset=None):
    payload = {"total": total, "data": [{"paperId": str(i), "title": f"Paper {i}"} for i in range(n_items)]}
    if next_offset is not None:
        payload["next"] = next_offset
    return payload


def test_semantic_scholar_search_sends_offset_and_limit():
    transport = FakeTransport(responses=[json_response(200, _s2_page(100, 25, next_offset=25))])
    adapter = SemanticScholarAdapter(transport=transport, cache=NullCache())

    result = adapter.search("transformers", page=1, page_size=25)

    assert transport.calls[0]["params"]["offset"] == 0
    assert transport.calls[0]["params"]["limit"] == 25
    assert result.page_info.has_more is True
    assert result.page_info.total == 100


def test_semantic_scholar_no_next_field_means_no_more_pages():
    transport = FakeTransport(responses=[json_response(200, _s2_page(5, 5))])
    adapter = SemanticScholarAdapter(transport=transport, cache=NullCache())
    result = adapter.search("x")
    assert result.page_info.has_more is False


def test_semantic_scholar_year_range_filter():
    transport = FakeTransport(responses=[json_response(200, _s2_page(0, 0))])
    adapter = SemanticScholarAdapter(transport=transport, cache=NullCache())
    adapter.search("x", SearchFilters(year_from=2019, year_to=2021))
    assert transport.calls[0]["params"]["year"] == "2019-2021"


def test_semantic_scholar_api_key_sent_as_header_not_query_param():
    from researchos.evidence.config import SourceConfig

    config = SourceConfig(source="semantic_scholar", base_url="https://api.semanticscholar.org/graph/v1", timeout=10, max_retries=1, api_key="secret-key-123")
    transport = FakeTransport(responses=[json_response(200, _s2_page(0, 0))])
    adapter = SemanticScholarAdapter(config=config, transport=transport, cache=NullCache())
    adapter.search("x")
    assert transport.calls[0]["headers"]["x-api-key"] == "secret-key-123"
    assert "secret-key-123" not in str(transport.calls[0]["params"])


# --- arXiv ----------------------------------------------------------------

_ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>2</opensearch:totalResults>
  <opensearch:startIndex>0</opensearch:startIndex>
  <opensearch:itemsPerPage>1</opensearch:itemsPerPage>
  <entry>
    <id>http://arxiv.org/abs/2101.00001v1</id>
    <title>First Paper</title>
    <summary>Summary one.</summary>
    <published>2021-01-01T00:00:00Z</published>
    <author><name>Jane Doe</name></author>
    <link rel="alternate" href="http://arxiv.org/abs/2101.00001v1"/>
    <category term="cs.LG"/>
  </entry>
</feed>"""


def test_arxiv_search_parses_atom_feed_and_pagination():
    transport = FakeTransport(responses=[text_response(200, _ARXIV_FEED)])
    adapter = ArxivAdapter(transport=transport, cache=NullCache())

    result = adapter.search("machine learning", page=1, page_size=1)

    assert transport.calls[0]["params"]["search_query"] == "all:machine learning"
    assert transport.calls[0]["params"]["start"] == 0
    assert transport.calls[0]["params"]["max_results"] == 1
    assert len(result.records) == 1
    assert result.records[0].title == "First Paper"
    assert result.page_info.total == 2
    assert result.page_info.has_more is True


def test_arxiv_author_and_year_range_filter_build_search_query():
    transport = FakeTransport(responses=[text_response(200, _ARXIV_FEED)])
    adapter = ArxivAdapter(transport=transport, cache=NullCache())
    adapter.search("x", SearchFilters(author="Jane Doe", year_from=2020, year_to=2021))
    query = transport.calls[0]["params"]["search_query"]
    assert "au:Jane Doe" in query
    assert "submittedDate:[20200101000000 TO 20211231235959]" in query


@pytest.mark.parametrize(
    "filters",
    [
        SearchFilters(venue="Nature"),
        SearchFilters(doi="10.1/x"),
        SearchFilters(document_type="article"),
    ],
)
def test_arxiv_raises_unsupported_filter_for_venue_doi_document_type(filters):
    adapter = ArxivAdapter(transport=FakeTransport(), cache=NullCache())
    with pytest.raises(UnsupportedFilterError):
        adapter.search("x", filters)
