"""Versioned prompt templates and JSON schemas for the analysis &
scientific review layer.

Every generation type has a stable `(prompt_name, prompt_version)` pair
persisted alongside its generated result — required for reproducibility
(Phase 8 spec section 22). Bumping a prompt's wording or schema means
adding a new `_v2` version, never silently editing `_v1` in place.

No schema here ever offers `approval_status`/`APPROVED` (for a
`ScientificClaim`) or `status`/`HUMAN_APPROVED`/`REJECTED` (for a
`ScientificReview`) as a settable field — `researchos.analysis.claims`/
`reviews` hard-code the LLM-reachable subset of each lifecycle
regardless of what a response contains, so there is structurally
nothing for an LLM to self-approve or self-reject with (Phase 8 spec
sections 14/19).
"""

from __future__ import annotations

import json
from typing import Any

_ANTI_HALLUCINATION_RULES = """
STRICT RULES — violating any of these makes your response invalid:
1. You may ONLY reference ids that appear in the CONTEXT JSON below.
   Never invent, guess, or reuse an id from outside it.
2. You calculate nothing yourself — every number in the CONTEXT JSON is
   already a computed fact. Your job is to interpret, not recompute.
3. Everything you produce is a CANDIDATE for human review: never a
   scientific conclusion, never an approved claim, never a settled
   scientific review. Use hedged, qualified language ("may suggest",
   "is consistent with") and never assert certainty a human has not
   confirmed.
4. Never turn "the metric value is higher" into "the method is
   scientifically better" — state only what the evidence shows and what
   it may suggest, and always surface missing evidence, threats to
   validity, and plausible alternative explanations alongside any
   candidate interpretation.
5. Respond with JSON only, matching the provided schema exactly. Do not
   include any approval/status field beyond what the schema explicitly
   allows, even if you believe a stronger status is warranted — final
   approval is exclusively a human decision made outside this response.
""".strip()


def _context_block(context_json: dict[str, Any]) -> str:
    return "CONTEXT JSON (the only prior content/ids you may reference):\n" + json.dumps(context_json, indent=2)


# ==========================================================================
# candidate_claim_generation.v1
# ==========================================================================

CLAIM_GENERATION_PROMPT_NAME = "candidate_claim_generation"
CLAIM_GENERATION_PROMPT_VERSION = "v1"

CLAIM_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "candidate_claim_generation_result",
    "properties": {
        "observations": {"type": "array", "items": {"type": "string"}},
        "missing_evidence": {"type": "array", "items": {"type": "string"}},
        "threats_to_validity": {"type": "array", "items": {"type": "string"}},
        "alternative_explanations": {"type": "array", "items": {"type": "string"}},
        "candidate_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_text": {"type": "string"},
                    "claim_type": {"type": "string"},
                    "confidence": {"type": "number"},
                    "supporting_analysis_record_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["claim_text", "supporting_analysis_record_ids"],
            },
        },
    },
    "required": ["candidate_claims"],
}


def build_claim_generation_prompt(context_json: dict[str, Any]) -> tuple[str, str]:
    system_text = (
        "You draft CANDIDATE scientific claims interpreting one or more already-computed, deterministic "
        "AnalysisRecord results for a research-management system. An AnalysisRecord's `result` is a computed "
        "fact (e.g. a difference, a mean, a ranking) — you are never asked to recompute it, only to describe "
        "what it may indicate and what a human reviewer should weigh before accepting it as scientific "
        "knowledge.\n\n"
        f"{_ANTI_HALLUCINATION_RULES}\n\n"
        "Every candidate claim must cite at least one of the given analysis_record_ids in "
        "supporting_analysis_record_ids — a claim resting on no supplied evidence is not a usable candidate. "
        "List observations, missing_evidence, threats_to_validity, and alternative_explanations as short, "
        "separate strings, not one paragraph, so a reviewer can evaluate each individually."
    )
    user_text = _context_block(context_json)
    return system_text, user_text


# ==========================================================================
# scientific_review_generation.v1
# ==========================================================================

REVIEW_GENERATION_PROMPT_NAME = "scientific_review_generation"
REVIEW_GENERATION_PROMPT_VERSION = "v1"

REVIEW_DIMENSION_KEYS = (
    "evidence_completeness",
    "experimental_consistency",
    "dataset_consistency",
    "metric_appropriateness",
    "baseline_adequacy",
    "ablation_coverage",
    "reproducibility",
    "statistical_support",
    "threats_to_validity",
    "claim_strength",
    "alternative_explanations",
    "missing_evidence",
)

# The LLM may only ever propose one of these three review statuses —
# CANDIDATE/NEEDS_MORE_EVIDENCE/READY_FOR_HUMAN_REVIEW are all
# non-authoritative, exactly matching ScientificReviewStatus's own
# docstring. HUMAN_APPROVED and REJECTED are never offered as a choice.
REVIEW_GENERATION_ALLOWED_STATUSES = ("candidate", "needs_more_evidence", "ready_for_human_review")

REVIEW_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "scientific_review_generation_result",
    "properties": {
        "dimensions": {
            "type": "object",
            "properties": {key: {"type": "string"} for key in REVIEW_DIMENSION_KEYS},
            "required": list(REVIEW_DIMENSION_KEYS),
        },
        "status": {"type": "string", "enum": list(REVIEW_GENERATION_ALLOWED_STATUSES)},
        "recommendation": {"type": "string"},
    },
    "required": ["dimensions", "status"],
}


def build_review_generation_prompt(context_json: dict[str, Any]) -> tuple[str, str]:
    system_text = (
        "You assess whether the evidence currently available adequately supports one CANDIDATE scientific "
        "claim for a research-management system. This is a SCIENTIFIC REVIEW, not a code review, not an "
        "execution review, and not a re-check of any metric calculation — assume every number given to you "
        "is already correct, and assess only whether it is enough to support the claim.\n\n"
        f"{_ANTI_HALLUCINATION_RULES}\n\n"
        "Assess every one of these twelve dimensions, each as a short, separate written assessment: "
        + ", ".join(REVIEW_DIMENSION_KEYS)
        + ". Set status to exactly one of 'candidate' (assessment still in progress), "
        "'needs_more_evidence' (the claim cannot yet be adequately assessed), or 'ready_for_human_review' "
        "(your assessment is complete and a human should now decide). You may never set status to "
        "'human_approved' or 'rejected' — those are exclusively human decisions made outside this response."
    )
    user_text = _context_block(context_json)
    return system_text, user_text
