"""Tests #9 (DOI normalization) and #10 (missing metadata / completeness),
as pure unit tests of `researchos.evidence.normalization`.
"""

from __future__ import annotations

import pytest

from researchos.evidence.normalization import (
    compute_metadata_completeness,
    first_author_surname,
    join_authors,
    normalize_doi,
    normalize_title,
    reconstruct_openalex_abstract,
    split_authors,
    strip_simple_xml_tags,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("10.1234/example", "10.1234/example"),
        ("https://doi.org/10.1234/EXAMPLE", "10.1234/example"),
        ("http://dx.doi.org/10.1234/Example", "10.1234/example"),
        ("doi:10.1234/example", "10.1234/example"),
        ("  10.1234/example  ", "10.1234/example"),
    ],
)
def test_normalize_doi_strips_prefixes_and_lowercases(raw, expected):
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "not-a-doi", "http://example.com/paper"])
def test_normalize_doi_returns_none_rather_than_fabricating(raw):
    assert normalize_doi(raw) is None


def test_normalize_title_is_case_and_punctuation_insensitive():
    assert normalize_title("Deep Learning: A Survey!") == normalize_title("deep learning a survey")


def test_normalize_title_of_none_is_empty_string():
    assert normalize_title(None) == ""


def test_first_author_surname_handles_family_given_and_given_family():
    assert first_author_surname(["Doe, Jane"]) == "doe"
    assert first_author_surname(["Jane Doe"]) == "doe"
    assert first_author_surname([]) is None
    assert first_author_surname([""]) is None


def test_join_and_split_authors_round_trip():
    authors = ["Jane Doe", "John Smith"]
    joined = join_authors(authors)
    assert joined == "Jane Doe; John Smith"
    assert split_authors(joined) == authors


def test_join_authors_of_empty_list_is_none():
    assert join_authors([]) is None


def test_split_authors_of_none_is_empty_list():
    assert split_authors(None) == []


def test_compute_metadata_completeness_full_vs_empty():
    full = dict(
        title="T", authors=["A"], year=2020, venue="V", doi="10.1/x", url="http://x", abstract="abs",
        document_type="article",
    )
    assert compute_metadata_completeness(full) == 1.0
    assert compute_metadata_completeness({}) == 0.0


def test_compute_metadata_completeness_is_fractional_for_partial_records():
    partial = dict(title="T", authors=[], year=None, venue=None, doi=None, url=None, abstract=None, document_type=None)
    completeness = compute_metadata_completeness(partial)
    assert 0.0 < completeness < 1.0


def test_reconstruct_openalex_abstract_restores_word_order():
    inverted = {"Hello": [0], "world": [1], "of": [3], "science": [4], "the": [2]}
    assert reconstruct_openalex_abstract(inverted) == "Hello world the of science"


def test_reconstruct_openalex_abstract_of_none_is_none():
    assert reconstruct_openalex_abstract(None) is None
    assert reconstruct_openalex_abstract({}) is None


def test_strip_simple_xml_tags_removes_jats_markup():
    assert strip_simple_xml_tags("<jats:p>Hello <jats:italic>world</jats:italic></jats:p>") == "Hello world"


def test_strip_simple_xml_tags_of_none_is_none():
    assert strip_simple_xml_tags(None) is None
