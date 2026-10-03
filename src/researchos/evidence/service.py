"""The evidence service: the only place in `researchos.evidence` that
touches the database. Adapters are pure I/O (network in, `NormalizedRecord`
out); this module persists what they return, resolves duplicates, and
writes the audit trail — ties together exactly the pipeline in
`docs/PHASE5_EVIDENCE.md`'s architecture diagram.

Nothing here calls an LLM. Nothing here decides whether a paper is
relevant, novel, or gap-filling — it only retrieves, normalizes,
deduplicates, and records bibliographic facts as reported by external
sources.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.errors import NotFoundError
from ..db.models import LiteratureItem, LiteratureMatch, RecordStatus
from .adapters import SourceAdapter, get_adapter
from .dedup import find_duplicate
from .errors import EvidenceError
from .normalization import join_authors
from .types import NormalizedRecord, SearchFilters, SearchResult


@dataclass(frozen=True)
class LiteratureSearchOutcome:
    result: SearchResult
    persisted_items: list[LiteratureItem]
    matches: list[LiteratureMatch]


@dataclass(frozen=True)
class GetByIdOutcome:
    record: Optional[NormalizedRecord]
    item: Optional[LiteratureItem]
    match: Optional[LiteratureMatch]


def _get_project_or_raise(session, project_id: int):
    project = repository.get_project(session, project_id)
    if project is None:
        raise NotFoundError(f"ResearchProject {project_id} does not exist.")
    return project


def _record_to_fields(record: NormalizedRecord) -> dict[str, Any]:
    return dict(
        title=record.title,
        authors=join_authors(record.authors),
        year=record.year,
        publication_date=record.publication_date,
        venue=record.venue,
        publisher=record.publisher,
        url=record.url,
        abstract=record.abstract,
        document_type=record.document_type,
        citation_count=record.citation_count,
        keywords=record.keywords or None,
        external_ids=record.external_ids or None,
        raw_metadata=record.raw_metadata or None,
        retrieved_at=record.retrieved_at,
        record_status=record.record_status,
        metadata_completeness=record.metadata_completeness,
    )


def _persist_record(session, project_id: int, record: NormalizedRecord) -> tuple[LiteratureItem, Optional[LiteratureMatch]]:
    """Insert or update one normalized record.

    Same (source, source_record_id) already stored -> idempotent update
    (re-fetching the same source's own record, not a duplicate). No
    prior record from this exact source -> run identity resolution
    (`researchos.evidence.dedup`); a match always inserts a *new* row
    (never overwrites/deletes the existing one — provenance from every
    source is preserved) and records a `LiteratureMatch` explaining why.
    """
    existing_same_source = repository.get_literature_item_by_source(
        session, project_id, record.source, record.source_record_id
    )
    if existing_same_source is not None:
        updated = repository.update_literature_item(session, existing_same_source.id, **_record_to_fields(record))
        return updated, None

    decision = find_duplicate(session, project_id, record)

    fields = _record_to_fields(record)
    if decision.is_duplicate:
        canonical = repository.get_literature_item(session, decision.duplicate_of_id)
        if canonical is not None and canonical.doi and record.doi == canonical.doi:
            # The existing (project_id, doi) uniqueness constraint (Phase 3)
            # would reject a second row with the same DOI. The DOI is not
            # lost — it remains in this row's raw_metadata/external_ids and
            # is explained by the LiteratureMatch row created below.
            fields["doi"] = None
        fields["record_status"] = RecordStatus.DUPLICATE_CANDIDATE
        fields["duplicate_of_id"] = decision.duplicate_of_id
    else:
        fields["doi"] = record.doi

    item = repository.add_literature_item(
        session, project_id=project_id, source=record.source, source_record_id=record.source_record_id, **fields
    )

    match = None
    if decision.is_duplicate:
        match = repository.record_literature_match(
            session,
            project_id=project_id,
            literature_item_id=item.id,
            matched_item_id=decision.duplicate_of_id,
            match_type=decision.match_type,
            confidence=decision.confidence,
            notes=decision.notes,
        )
    return item, match


def _filters_to_metadata(filters: SearchFilters) -> dict[str, Any]:
    return {k: v for k, v in asdict(filters).items() if v is not None}


def search_literature(
    project_id: int,
    source: str,
    query: str,
    filters: Optional[SearchFilters] = None,
    *,
    page: int = 1,
    page_size: int = 25,
    actor: str,
    persist: bool = True,
    adapter: Optional[SourceAdapter] = None,
    session_factory: Optional[sessionmaker] = None,
) -> LiteratureSearchOutcome:
    """Search one source, optionally persisting results into `project_id`'s
    literature pool. Always writes an `evidence.search` audit event —
    on success or on failure — with the query, filters, pagination, and
    result count, but never an API key or contact email.
    """
    filters = filters or SearchFilters()
    resolved_adapter = adapter or get_adapter(source)

    try:
        result = resolved_adapter.search(query, filters, page=page, page_size=page_size)
    except EvidenceError as exc:
        with session_scope(session_factory) as session:
            _get_project_or_raise(session, project_id)
            repository.append_audit_event(
                session,
                project_id=project_id,
                event_type="evidence.search",
                actor=actor,
                description=f"Search of {source} for '{query}' failed: {exc}",
                metadata={
                    "source": source,
                    "query": query,
                    "filters": _filters_to_metadata(filters),
                    "page": page,
                    "page_size": page_size,
                    "error": str(exc),
                },
            )
        raise

    persisted_items: list[LiteratureItem] = []
    matches: list[LiteratureMatch] = []
    with session_scope(session_factory) as session:
        _get_project_or_raise(session, project_id)
        if persist:
            for record in result.records:
                item, match = _persist_record(session, project_id, record)
                persisted_items.append(item)
                if match is not None:
                    matches.append(match)

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="evidence.search",
            actor=actor,
            description=f"Searched {source} for '{query}': {len(result.records)} result(s)"
            + (f", {len(persisted_items)} persisted" if persist else ", not persisted"),
            metadata={
                "source": source,
                "query": query,
                "filters": _filters_to_metadata(filters),
                "page": result.page_info.page,
                "page_size": result.page_info.page_size,
                "total": result.page_info.total,
                "has_more": result.page_info.has_more,
                "result_count": len(result.records),
                "persisted_count": len(persisted_items),
                "duplicate_count": len(matches),
            },
        )

    return LiteratureSearchOutcome(result=result, persisted_items=persisted_items, matches=matches)


def get_literature_by_id(
    project_id: int,
    source: str,
    source_record_id: str,
    *,
    actor: str,
    persist: bool = True,
    adapter: Optional[SourceAdapter] = None,
    session_factory: Optional[sessionmaker] = None,
) -> GetByIdOutcome:
    """Fetch one record by its source-native id. `record is None` means a
    genuine not-found (`RecordStatus.NOT_FOUND` semantics) — nothing is
    persisted in that case. Always writes an `evidence.get_by_id` audit
    event, on success, not-found, or failure.
    """
    resolved_adapter = adapter or get_adapter(source)

    try:
        record = resolved_adapter.get_by_id(source_record_id)
    except EvidenceError as exc:
        with session_scope(session_factory) as session:
            _get_project_or_raise(session, project_id)
            repository.append_audit_event(
                session,
                project_id=project_id,
                event_type="evidence.get_by_id",
                actor=actor,
                description=f"Lookup of {source}:{source_record_id} failed: {exc}",
                metadata={"source": source, "source_record_id": source_record_id, "error": str(exc)},
            )
        raise

    item: Optional[LiteratureItem] = None
    match: Optional[LiteratureMatch] = None
    with session_scope(session_factory) as session:
        _get_project_or_raise(session, project_id)
        if record is not None and persist:
            item, match = _persist_record(session, project_id, record)

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="evidence.get_by_id",
            actor=actor,
            description=f"Lookup of {source}:{source_record_id}: " + ("found" if record is not None else "not found"),
            metadata={
                "source": source,
                "source_record_id": source_record_id,
                "found": record is not None,
                "persisted": item is not None,
            },
        )

    return GetByIdOutcome(record=record, item=item, match=match)
