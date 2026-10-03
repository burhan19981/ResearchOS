"""Tests #17 (invalid responses) and #18 (source errors)."""

from __future__ import annotations

import socket
import urllib.error

import pytest

from researchos.evidence._http import UrllibTransport
from researchos.evidence.adapters.arxiv import ArxivAdapter
from researchos.evidence.adapters.crossref import CrossrefAdapter
from researchos.evidence.adapters.openalex import OpenAlexAdapter
from researchos.evidence.adapters.semantic_scholar import SemanticScholarAdapter
from researchos.evidence.cache import NullCache
from researchos.evidence.errors import SourceResponseError, SourceTimeoutError, SourceUnavailableError

from .fakes import FakeTransport, json_response, text_response


@pytest.mark.parametrize(
    "adapter_cls",
    [OpenAlexAdapter, CrossrefAdapter, SemanticScholarAdapter],
)
def test_malformed_json_raises_source_response_error(adapter_cls):
    transport = FakeTransport(responses=[text_response(200, "{not valid json")])
    adapter = adapter_cls(transport=transport, cache=NullCache())
    with pytest.raises(SourceResponseError):
        adapter.search("x")


@pytest.mark.parametrize("adapter_cls", [OpenAlexAdapter, CrossrefAdapter, SemanticScholarAdapter])
def test_json_array_instead_of_object_raises_source_response_error(adapter_cls):
    transport = FakeTransport(responses=[text_response(200, "[1, 2, 3]")])
    adapter = adapter_cls(transport=transport, cache=NullCache())
    with pytest.raises(SourceResponseError):
        adapter.search("x")


def test_arxiv_malformed_xml_raises_source_response_error():
    transport = FakeTransport(responses=[text_response(200, "<not><valid</xml>")])
    adapter = ArxivAdapter(transport=transport, cache=NullCache())
    with pytest.raises(SourceResponseError):
        adapter.search("x")


@pytest.mark.parametrize(
    "adapter_cls,make_config_kwargs",
    [
        (OpenAlexAdapter, {}),
        (CrossrefAdapter, {}),
        (SemanticScholarAdapter, {}),
    ],
)
def test_404_on_get_by_id_returns_none_not_an_exception(adapter_cls, make_config_kwargs):
    transport = FakeTransport(responses=[json_response(404, {"error": "not found"})])
    adapter = adapter_cls(transport=transport, cache=NullCache())
    assert adapter.get_by_id("does-not-exist") is None


_ARXIV_ERROR_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>0</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format_for_doesnotexist</id>
    <title>Error</title>
    <summary>incorrect id format for doesnotexist</summary>
  </entry>
</feed>"""


def test_arxiv_unknown_id_error_entry_returns_none():
    """arXiv returns HTTP 200 with a special error entry for unknown ids,
    not a 404 — this must still surface as 'not found' (None) to callers."""
    transport = FakeTransport(responses=[text_response(200, _ARXIV_ERROR_FEED)])
    adapter = ArxivAdapter(transport=transport, cache=NullCache())
    assert adapter.get_by_id("doesnotexist") is None


def test_urllib_transport_translates_connection_error():
    """A real (simulated) low-level connection failure must become a
    normalized SourceUnavailableError, not a raw urllib exception."""
    import unittest.mock as mock

    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
        transport = UrllibTransport()
        with pytest.raises(SourceUnavailableError):
            transport.get("https://example.test/x", timeout=1.0)


def test_urllib_transport_translates_socket_timeout():
    import unittest.mock as mock

    with mock.patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
        transport = UrllibTransport()
        with pytest.raises(SourceTimeoutError):
            transport.get("https://example.test/x", timeout=1.0)


def test_urllib_transport_translates_urlerror_wrapping_a_timeout():
    import unittest.mock as mock

    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError(socket.timeout("timed out"))):
        transport = UrllibTransport()
        with pytest.raises(SourceTimeoutError):
            transport.get("https://example.test/x", timeout=1.0)
