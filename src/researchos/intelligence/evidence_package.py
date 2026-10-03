"""Deterministic, bounded evidence package construction.

Turns a list of `LiteratureItem` ids into the narrow, LLM-safe
projection defined by `EvidencePackageItem` — never the raw ORM row,
never arbitrary database fields the Phase 6 spec didn't ask for (e.g.
internal `raw_metadata`, `evidence_status` review notes beyond the
status itself). Ranking and truncation are both deterministic and
always explicit — never a silent drop.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..db import repository
from ..db.models import LiteratureItem
from ..evidence.normalization import split_authors
from .errors import EvidencePackageError
from .types import EvidencePackage, EvidencePackageItem

DEFAULT_MAX_ITEMS = 20
DEFAULT_MAX_ABSTRACT_CHARS = 2000


def _to_package_item(item: LiteratureItem, *, max_abstract_chars: int) -> EvidencePackageItem:
    abstract = item.abstract
    truncated = False
    if abstract and len(abstract) > max_abstract_chars:
        abstract = abstract[:max_abstract_chars]
        truncated = True

    return EvidencePackageItem(
        literature_item_id=item.id,
        source=item.source,
        source_record_id=item.source_record_id,
        title=item.title,
        authors=split_authors(item.authors),
        year=item.year,
        publication_date=item.publication_date.isoformat() if item.publication_date else None,
        venue=item.venue,
        doi=item.doi,
        abstract=abstract,
        citation_count=item.citation_count,
        keywords=list(item.keywords or []),
        metadata_completeness=item.metadata_completeness,
        evidence_status=item.evidence_status.value,
        retrieved_at=item.retrieved_at.isoformat() if item.retrieved_at else None,
        url=item.url,
        abstract_truncated=truncated,
    )


def _ranking_key(item: LiteratureItem) -> tuple[float, int]:
    """Deterministic ranking when truncation is needed: more-complete
    metadata first, ties broken by id (stable, reproducible ordering)."""
    completeness = item.metadata_completeness if item.metadata_completeness is not None else 0.0
    return (-completeness, item.id)


def build_evidence_package(
    session: Session,
    project_id: int,
    literature_item_ids: list[int],
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_abstract_chars: int = DEFAULT_MAX_ABSTRACT_CHARS,
) -> EvidencePackage:
    """Build a bounded evidence package from explicitly-selected literature items.

    Every id in `literature_item_ids` must resolve to a `LiteratureItem`
    that belongs to `project_id` — an unknown or cross-project id raises
    `EvidencePackageError` immediately rather than silently skipping it
    (silently dropping a caller's explicit selection would be exactly the
    kind of silent omission Phase 6 forbids).
    """
    if not literature_item_ids:
        raise EvidencePackageError("At least one literature_item_id must be provided.")

    resolved: list[LiteratureItem] = []
    for item_id in literature_item_ids:
        item = repository.get_literature_item(session, item_id)
        if item is None or item.project_id != project_id:
            raise EvidencePackageError(
                f"LiteratureItem {item_id} does not exist in project {project_id}; "
                "cannot silently omit an explicitly-selected id."
            )
        resolved.append(item)

    truncated = len(resolved) > max_items
    if truncated:
        ordered = sorted(resolved, key=_ranking_key)
        included = ordered[:max_items]
        excluded = ordered[max_items:]
    else:
        included = resolved
        excluded = []

    # Preserve the caller's original selection order among included items,
    # rather than the ranking order, so results read naturally.
    included_ids = {item.id for item in included}
    included_in_original_order = [item for item in resolved if item.id in included_ids]

    package_items = [_to_package_item(item, max_abstract_chars=max_abstract_chars) for item in included_in_original_order]

    return EvidencePackage(
        requested_item_ids=list(literature_item_ids),
        items=package_items,
        truncated=truncated,
        excluded_item_ids=[item.id for item in excluded],
        max_items=max_items,
        max_abstract_chars=max_abstract_chars,
    )
