"""Analysis context package assembly (Phase 8 spec section 20).

Turns explicitly-supplied `AnalysisRecord`/`ScientificClaim` ids into
the bounded, explicit `AnalysisContext`/`ReviewContext` each
LLM-assisted generation service sends to a provider — never the raw
ORM row, never arbitrary internal fields, never "the latest analysis"
inferred implicitly.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..db import repository
from ..planning import orchestration
from .errors import MissingEntityError
from .types import AnalysisContext, ReviewContext


def _project_or_raise(session: Session, project_id: int) -> Any:
    project = repository.get_project(session, project_id)
    if project is None:
        raise MissingEntityError(f"ResearchProject {project_id} does not exist.")
    return project


def _analysis_record_json(session: Session, project_id: int, analysis_record_id: int) -> dict[str, Any]:
    record = repository.get_analysis_record(session, analysis_record_id)
    orchestration.require_in_project(record, analysis_record_id, "AnalysisRecord", project_id)
    inputs = repository.list_analysis_inputs(session, project_id, analysis_record_id=record.id)
    return {
        "analysis_record_id": record.id,
        "method": record.method,
        "parameters": record.parameters,
        "result": record.result,
        "status": record.status.value,
        "version": record.version,
        "inputs": [{"input_type": i.input_type.value, "input_id": i.input_id} for i in inputs],
    }


def build_claim_context(session: Session, project_id: int, analysis_record_ids: list[int]) -> AnalysisContext:
    """Rules for candidate-claim generation: every `analysis_record_id`
    is explicit and must exist in this project — the LLM is never
    handed "recent analyses" implicitly (Phase 8 spec section 8)."""
    _project_or_raise(session, project_id)
    records_json = []
    upstream_snapshots: dict[str, Any] = {}
    for analysis_record_id in analysis_record_ids:
        record_json = _analysis_record_json(session, project_id, analysis_record_id)
        records_json.append(record_json)
        upstream_snapshots[f"analysis_record:{analysis_record_id}"] = {
            "id": record_json["analysis_record_id"],
            "version": record_json["version"],
            "status": record_json["status"],
        }
    prompt_json = {"analysis_records": records_json}
    return AnalysisContext(
        prompt_json=prompt_json,
        allowed_analysis_record_ids=frozenset(analysis_record_ids),
        upstream_snapshots=upstream_snapshots,
    )


def build_review_context(session: Session, project_id: int, claim_id: int) -> ReviewContext:
    """Rules for scientific-review generation: the reviewed claim and
    its already-linked supporting `AnalysisRecord` evidence (via
    `ScientificClaimAnalysis`) are the *only* content the LLM sees —
    it is never handed the raw database, only what this claim actually
    cites."""
    _project_or_raise(session, project_id)
    claim = repository.get_scientific_claim(session, claim_id)
    orchestration.require_in_project(claim, claim_id, "ScientificClaim", project_id)

    links = repository.list_scientific_claim_analyses(session, project_id, claim_id=claim_id)
    analysis_record_ids = [link.analysis_record_id for link in links]

    records_json = []
    upstream_snapshots: dict[str, Any] = {
        "scientific_claim": {"id": claim.id, "version": claim.version, "approval_status": claim.approval_status.value},
    }
    for analysis_record_id in analysis_record_ids:
        record_json = _analysis_record_json(session, project_id, analysis_record_id)
        records_json.append(record_json)
        upstream_snapshots[f"analysis_record:{analysis_record_id}"] = {
            "id": record_json["analysis_record_id"],
            "version": record_json["version"],
            "status": record_json["status"],
        }

    prompt_json = {
        "claim": {
            "claim_id": claim.id,
            "claim_text": claim.claim_text,
            "claim_type": claim.claim_type,
            "strength": claim.strength.value,
            "confidence": claim.confidence,
        },
        "supporting_analysis_records": records_json,
    }
    return ReviewContext(
        prompt_json=prompt_json,
        allowed_analysis_record_ids=frozenset(analysis_record_ids),
        upstream_snapshots=upstream_snapshots,
    )
