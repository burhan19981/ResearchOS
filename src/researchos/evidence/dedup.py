"""Deterministic identity resolution for literature records.

Preferred signal order, per `docs/PHASE5_EVIDENCE.md`:

1. DOI (normalized) — confidence 1.0.
2. A strong external identifier shared between the candidate and an
   existing record (either record's own `(source, source_record_id)`,
   or an identifier embedded in either record's `external_ids`) —
   confidence 0.95.
3. Normalized title + first-author surname + year — a *weak* fallback,
   confidence 0.6, always recorded as a `DUPLICATE_CANDIDATE`, never
   silently merged.

This module never deletes or merges a `LiteratureItem` — it only
decides whether a `LiteratureMatch` should be recorded, pointing the
new record at an existing "canonical" one, with a confidence and a
human-readable explanation of exactly which signal matched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from ..db import repository
from ..db.models import LiteratureItem, MatchType
from .normalization import first_author_surname, normalize_title, split_authors
from .types import NormalizedRecord

DOI_MATCH_CONFIDENCE = 1.0
SOURCE_ID_MATCH_CONFIDENCE = 0.95
TITLE_AUTHOR_YEAR_MATCH_CONFIDENCE = 0.6


@dataclass(frozen=True)
class DuplicateDecision:
    duplicate_of_id: Optional[int]
    match_type: Optional[MatchType]
    confidence: Optional[float]
    notes: Optional[str]

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of_id is not None


_NO_MATCH = DuplicateDecision(duplicate_of_id=None, match_type=None, confidence=None, notes=None)


def _check_doi(existing_items: list[LiteratureItem], candidate: NormalizedRecord) -> Optional[DuplicateDecision]:
    if not candidate.doi:
        return None
    for item in existing_items:
        if item.doi and item.doi == candidate.doi:
            return DuplicateDecision(
                duplicate_of_id=item.id,
                match_type=MatchType.DOI,
                confidence=DOI_MATCH_CONFIDENCE,
                notes=f"Exact DOI match: {candidate.doi}",
            )
    return None


def _check_strong_identifier(
    existing_items: list[LiteratureItem], candidate: NormalizedRecord
) -> Optional[DuplicateDecision]:
    candidate_ids = dict(candidate.external_ids)
    candidate_ids.setdefault(candidate.source, candidate.source_record_id)

    for item in existing_items:
        item_ids = dict(item.external_ids or {})
        if item.source and item.source_record_id:
            item_ids.setdefault(item.source, item.source_record_id)

        for id_type, id_value in candidate_ids.items():
            if not id_value:
                continue
            if item_ids.get(id_type) == id_value:
                return DuplicateDecision(
                    duplicate_of_id=item.id,
                    match_type=MatchType.SOURCE_ID,
                    confidence=SOURCE_ID_MATCH_CONFIDENCE,
                    notes=f"Shared '{id_type}' identifier ({id_value}) with an existing {item.source} record.",
                )
    return None


def _check_title_author_year(
    existing_items: list[LiteratureItem], candidate: NormalizedRecord
) -> Optional[DuplicateDecision]:
    if not candidate.year:
        return None
    candidate_title_key = normalize_title(candidate.title)
    if not candidate_title_key:
        return None
    candidate_author_key = first_author_surname(candidate.authors)
    if not candidate_author_key:
        return None

    for item in existing_items:
        if item.year != candidate.year:
            continue
        if normalize_title(item.title) != candidate_title_key:
            continue
        item_author_key = first_author_surname(split_authors(item.authors))
        if item_author_key and item_author_key == candidate_author_key:
            return DuplicateDecision(
                duplicate_of_id=item.id,
                match_type=MatchType.TITLE_AUTHOR_YEAR,
                confidence=TITLE_AUTHOR_YEAR_MATCH_CONFIDENCE,
                notes=(
                    f"Normalized title + first-author surname ('{candidate_author_key}') + year "
                    f"({candidate.year}) match an existing record — a weak signal, recorded as a "
                    "candidate only, not merged."
                ),
            )
    return None


def find_duplicate(session: Session, project_id: int, candidate: NormalizedRecord) -> DuplicateDecision:
    """Check `candidate` against every existing literature item in the
    project, in preferred-signal order. Returns `_NO_MATCH` (a
    decision with `is_duplicate is False`) if nothing matches.

    O(n) in the project's current literature item count — acceptable at
    Phase 5's scale; see docs/PHASE5_EVIDENCE.md's Limitations section
    for the scaling note.
    """
    existing_items = repository.list_literature_items(session, project_id)
    for check in (_check_doi, _check_strong_identifier, _check_title_author_year):
        decision = check(existing_items, candidate)
        if decision is not None:
            return decision
    return _NO_MATCH
