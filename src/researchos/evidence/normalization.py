"""Pure, dependency-free normalization helpers shared by every adapter.

Nothing here calls a network or a database — these are small, testable
functions that turn a source's raw representation of a field into the
`NormalizedRecord` shape without ever inventing a value that wasn't
supplied.
"""

from __future__ import annotations

import re
from typing import Any, Optional

_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi.org/",
    "doi:",
)
_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")

_COMPLETENESS_FIELDS = ("title", "authors", "year", "venue", "doi", "url", "abstract", "document_type")


def normalize_doi(raw: Optional[str]) -> Optional[str]:
    """Normalize a DOI to lowercase, prefix-stripped canonical form.

    Returns `None` (never a guessed/fabricated value) if `raw` is empty
    or doesn't have the basic `10.NNNN/suffix` shape after stripping a
    known URL/scheme prefix.
    """
    if not raw:
        return None
    value = raw.strip()
    lowered = value.lower()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            value = value[len(prefix) :]
            break
    value = value.strip().lower()
    if not value or not _DOI_PATTERN.match(value):
        return None
    return value


def normalize_title(title: Optional[str]) -> str:
    """Lowercase, punctuation-stripped, whitespace-collapsed title, for
    fuzzy (never exact-identity) comparison only."""
    if not title:
        return ""
    value = title.lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


_AUTHOR_SEPARATOR = "; "


def join_authors(authors: list[str]) -> Optional[str]:
    """Join a `NormalizedRecord.authors` list into the single Text field
    `LiteratureItem.authors` uses (a Phase 3 design choice kept as-is —
    see docs/PHASE5_EVIDENCE.md). `split_authors()` reverses this exactly."""
    cleaned = [author.strip() for author in authors if author and author.strip()]
    return _AUTHOR_SEPARATOR.join(cleaned) if cleaned else None


def split_authors(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(_AUTHOR_SEPARATOR) if part.strip()]


def first_author_surname(authors: list[str]) -> Optional[str]:
    """A best-effort surname key from the first author string, for the
    weak title+author+year dedup fallback only — never used to assert identity."""
    if not authors:
        return None
    first = authors[0].strip()
    if not first:
        return None
    if "," in first:
        surname = first.split(",", 1)[0]
    else:
        parts = first.split()
        surname = parts[-1] if parts else first
    surname = surname.strip().lower()
    return surname or None


def compute_metadata_completeness(fields: dict[str, Any]) -> float:
    """Fraction of `_COMPLETENESS_FIELDS` present (non-empty) in `fields`.

    A simple, deterministic, explainable score — not a claim of
    correctness, only of how much of the expected shape the source
    actually supplied.
    """
    present = sum(1 for name in _COMPLETENESS_FIELDS if fields.get(name))
    return present / len(_COMPLETENESS_FIELDS)


def reconstruct_openalex_abstract(inverted_index: Optional[dict[str, list[int]]]) -> Optional[str]:
    """OpenAlex stores abstracts as a word -> [positions] inverted index
    (to avoid abstract-reuse copyright concerns) rather than plain text.
    This reconstructs the original word order losslessly when present."""
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, indexes in inverted_index.items():
        for index in indexes:
            positions[index] = word
    if not positions:
        return None
    return " ".join(positions[i] for i in sorted(positions))


def strip_simple_xml_tags(value: Optional[str]) -> Optional[str]:
    """Best-effort plain text from an occasionally JATS-XML-tagged
    Crossref abstract. Never used on anything larger than one field's
    text, and never used to execute or interpret markup."""
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None
