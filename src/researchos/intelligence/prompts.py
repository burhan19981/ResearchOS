"""Versioned prompt templates and JSON schemas for the research
intelligence layer.

Every analysis type has a stable `(prompt_name, prompt_version)` pair
persisted alongside its generated result — required for reproducibility
(Phase 6 spec section 11). Bumping a prompt's wording or schema means
adding a new `_V2` version, never silently editing `_V1` in place, so a
previously-generated analysis's provenance always points at the exact
prompt text that produced it.

No API key or secret is ever interpolated into a prompt.
"""

from __future__ import annotations

import json
from typing import Any

from .types import ANALYSIS_DIMENSIONS, EvidencePackage

# --------------------------------------------------------------------------
# Shared anti-hallucination instruction, reused by every prompt below.
# --------------------------------------------------------------------------

_ANTI_HALLUCINATION_RULES = """
STRICT RULES — violating any of these makes your response invalid:
1. You may ONLY reference literature_item_id values that appear in the
   EVIDENCE JSON below. Never invent, guess, or reuse an id from outside it.
2. Never invent a DOI, author name, title, publication date, dataset, or
   citation that is not present in the supplied evidence. If it is not
   present, do not mention it as fact.
3. If a requested piece of information is absent from the supplied
   title/abstract/metadata for a paper, you MUST return the literal
   string "unknown" for that field — never fill it in from your own
   training knowledge of the paper or topic.
4. Everything you produce is a CANDIDATE for human review, not an
   established fact. Use hedged, evidence-qualified language (e.g.
   "based on the retrieved literature", "the supplied abstract suggests").
   Never assert certainty a human has not confirmed.
5. Respond with JSON only, matching the provided schema exactly.
""".strip()


def _evidence_block(package: EvidencePackage) -> str:
    payload = package.to_prompt_json_ready()
    note = ""
    if package.truncated:
        note = (
            f"\nNOTE: {len(package.excluded_item_ids)} additional matching item(s) were "
            "excluded from this package due to the configured evidence limit — your "
            "analysis is based only on the items below, and you must not claim "
            "completeness beyond them."
        )
    return "EVIDENCE JSON (the only literature you may reference):\n" + json.dumps(payload, indent=2) + note


# ==========================================================================
# literature_analysis.v1
# ==========================================================================

LITERATURE_ANALYSIS_PROMPT_NAME = "literature_analysis"
LITERATURE_ANALYSIS_PROMPT_VERSION = "v1"

LITERATURE_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "literature_analysis_result",
    "properties": {
        "items": {
            "type": "object",
            "description": "Keyed by literature_item_id (as a string). One entry per evidence item.",
            "additionalProperties": {
                "type": "object",
                "properties": {name: {"type": "string"} for name in ANALYSIS_DIMENSIONS},
            },
        },
        "claims": {
            "type": "array",
            "description": "Zero or more traceable analytical claims distilled from the evidence.",
            "items": {
                "type": "object",
                "properties": {
                    "claim_text": {"type": "string"},
                    "claim_type": {"type": "string"},
                    "support_level": {
                        "type": "string",
                        "enum": ["supported", "partially_supported", "unsupported_candidate"],
                    },
                    "evidence_item_ids": {"type": "array", "items": {"type": "integer"}},
                    "confidence": {"type": "number"},
                    "uncertainty": {"type": "string"},
                },
                "required": ["claim_text", "support_level", "evidence_item_ids"],
            },
        },
    },
    "required": ["items", "claims"],
}


def build_literature_analysis_prompt(
    package: EvidencePackage, *, research_topic: str, objective: str | None
) -> tuple[str, str]:
    """Returns (system_text, user_text) for a literature_analysis.v1 call."""
    system_text = (
        "You are a literature-analysis assistant for a research-management system. "
        "You analyze already-retrieved scholarly evidence; you do not search for or "
        "invent papers. Every fact you state must trace back to the supplied evidence.\n\n"
        f"{_ANTI_HALLUCINATION_RULES}\n\n"
        "For each evidence item, fill in these dimensions using only that item's own "
        f"title/abstract/metadata: {', '.join(ANALYSIS_DIMENSIONS)}. "
        "Use \"unknown\" for any dimension the abstract/metadata does not address."
    )
    user_text = (
        f"RESEARCH TOPIC: {research_topic}\n"
        f"OBJECTIVE: {objective or '(none specified)'}\n\n"
        f"{_evidence_block(package)}"
    )
    return system_text, user_text


# ==========================================================================
# gap_analysis.v1
# ==========================================================================

GAP_ANALYSIS_PROMPT_NAME = "gap_analysis"
GAP_ANALYSIS_PROMPT_VERSION = "v1"

GAP_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "gap_analysis_result",
    "properties": {
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "gap_statement": {"type": "string"},
                    "gap_type": {"type": "string"},
                    "affected_research_area": {"type": "string"},
                    "supporting_literature_ids": {"type": "array", "items": {"type": "integer"}},
                    "contradicting_literature_ids": {"type": "array", "items": {"type": "integer"}},
                    "evidence_summary": {"type": "string"},
                    "uncertainty": {"type": "string"},
                    "confidence": {"type": "number"},
                    "prior_work_summary": {"type": "string"},
                    "insufficiency_summary": {"type": "string"},
                    "missing_evidence_summary": {"type": "string"},
                    "candidate_research_question": {"type": "string"},
                },
                "required": ["gap_statement", "supporting_literature_ids"],
            },
        }
    },
    "required": ["gaps"],
}

_GAP_TYPE_EXAMPLES = (
    "methodological, dataset, evaluation, domain/application, scalability, "
    "robustness, reproducibility, comparison, temporal, deployment, "
    "theoretical, integration"
)


def build_gap_analysis_prompt(package: EvidencePackage, *, research_topic: str) -> tuple[str, str]:
    """Returns (system_text, user_text) for a gap_analysis.v1 call."""
    system_text = (
        "You identify CANDIDATE research gaps from already-retrieved scholarly evidence "
        "for a research-management system. You never declare a gap confirmed — every gap "
        "you produce is a candidate a human must review and approve.\n\n"
        f"{_ANTI_HALLUCINATION_RULES}\n\n"
        f"gap_type is a free-text category; examples include: {_GAP_TYPE_EXAMPLES}. "
        "These are categories to help a human triage, not conclusions. Every gap must cite "
        "at least one supporting_literature_ids entry from the evidence."
    )
    user_text = f"RESEARCH TOPIC: {research_topic}\n\n{_evidence_block(package)}"
    return system_text, user_text


# ==========================================================================
# novelty_analysis.v1
# ==========================================================================

NOVELTY_ANALYSIS_PROMPT_NAME = "novelty_analysis"
NOVELTY_ANALYSIS_PROMPT_VERSION = "v1"

# Deliberately excludes "human_approved" — the LLM must never be able to
# self-assign the one status that represents a settled, human-confirmed
# outcome. This is enforced structurally here (the schema's enum simply
# doesn't offer it) and re-checked defensively in code, since JSON-schema
# enforcement strictness varies by provider.
NOVELTY_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "novelty_analysis_result",
    "properties": {
        "comparisons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "literature_item_id": {"type": "integer"},
                    "similarity": {"type": "string"},
                    "difference": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["similar", "partially_distinct", "distinct", "unclear"],
                    },
                    "similarity_evidence_ids": {"type": "array", "items": {"type": "integer"}},
                    "difference_evidence_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["literature_item_id", "status"],
            },
        },
        "potentially_novel_elements": {"type": "string"},
        "potentially_existing_elements": {"type": "string"},
        "unresolved_questions": {"type": "string"},
        "novelty_risk": {"type": "string"},
        "confidence": {"type": "number"},
        "candidate_status": {
            "type": "string",
            "enum": [
                "not_assessed",
                "possibly_already_existing",
                "partially_distinct",
                "potentially_distinct",
                "insufficient_evidence",
            ],
        },
    },
    "required": ["comparisons", "candidate_status"],
}


def build_novelty_analysis_prompt(package: EvidencePackage, *, proposed_contribution: str) -> tuple[str, str]:
    """Returns (system_text, user_text) for a novelty_analysis.v1 call."""
    system_text = (
        "You compare a proposed research contribution against already-retrieved prior "
        "work for a research-management system. You are NOT a novelty detector that "
        "issues a final yes/no verdict — you produce an evidence-qualified analysis a "
        "human must review. Never output a bare 'Novel: Yes' or equivalent unqualified "
        "claim; always hedge with language like 'potentially distinct based on the "
        "retrieved literature, but additional verification is required.'\n\n"
        f"{_ANTI_HALLUCINATION_RULES}\n\n"
        "For each evidence item, produce one entry in `comparisons` describing how the "
        "proposed contribution relates to that specific prior work. candidate_status "
        "must be your OVERALL assessment across all comparisons — never "
        "'human_approved', which only a human reviewer may ever set."
    )
    user_text = f"PROPOSED CONTRIBUTION: {proposed_contribution}\n\n{_evidence_block(package)}"
    return system_text, user_text
