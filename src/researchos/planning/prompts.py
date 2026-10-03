"""Versioned prompt templates and JSON schemas for the research planning
layer.

Every generation type has a stable `(prompt_name, prompt_version)` pair
persisted alongside its generated result — required for reproducibility,
matching Phase 6 spec section 11's precedent. Bumping a prompt's wording
or schema means adding a new `_v2` version, never silently editing
`_v1` in place, so a previously-generated plan's provenance always
points at the exact prompt text that produced it.

No API key or secret is ever interpolated into a prompt. No schema here
ever offers `planning_status`/`APPROVED` as a settable field — every
generation service hard-codes `PlanningApprovalStatus.CANDIDATE` when
persisting, regardless of what a response contains, so there is
structurally nothing for an LLM to self-approve.
"""

from __future__ import annotations

import json
from typing import Any

_ANTI_HALLUCINATION_RULES = """
STRICT RULES — violating any of these makes your response invalid:
1. You may ONLY reference ids that appear in the CONTEXT JSON below.
   Never invent, guess, or reuse an id from outside it.
2. Never invent a DOI, author name, title, dataset, or citation that is
   not present in the supplied context. If it is not present, do not
   mention it as fact.
3. Everything you produce is a CANDIDATE for human review, not an
   approved plan, not a scientifically validated methodology, and not a
   claim of novelty. Use hedged, qualified language. Never assert
   certainty a human has not confirmed, and never claim your proposal
   is scientifically correct.
4. Respond with JSON only, matching the provided schema exactly. Do not
   include any status/approval field even if you believe one is
   warranted — approval is exclusively a human decision made outside
   this response.
""".strip()


def _context_block(context_json: dict[str, Any]) -> str:
    return "CONTEXT JSON (the only prior content/ids you may reference):\n" + json.dumps(context_json, indent=2)


# ==========================================================================
# research_question_generation.v1
# ==========================================================================

RESEARCH_QUESTION_GENERATION_PROMPT_NAME = "research_question_generation"
RESEARCH_QUESTION_GENERATION_PROMPT_VERSION = "v1"

RESEARCH_QUESTION_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "research_question_generation_result",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "hypothesis": {"type": "string"},
                    "type": {"type": "string"},
                    "cited_literature_item_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["question"],
            },
        }
    },
    "required": ["questions"],
}


def build_research_question_generation_prompt(context_json: dict[str, Any]) -> tuple[str, str]:
    system_text = (
        "You propose CANDIDATE research questions from one already-approved research gap for a "
        "research-management system. You never declare a question settled — every question you "
        "produce is a candidate a human must review and approve.\n\n"
        f"{_ANTI_HALLUCINATION_RULES}\n\n"
        "A hypothesis is optional — include one only when it is scientifically appropriate for the "
        "question (not every research question implies a testable hypothesis)."
    )
    user_text = _context_block(context_json)
    return system_text, user_text


# ==========================================================================
# contribution_generation.v1
# ==========================================================================

CONTRIBUTION_GENERATION_PROMPT_NAME = "contribution_generation"
CONTRIBUTION_GENERATION_PROMPT_VERSION = "v1"

CONTRIBUTION_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "contribution_generation_result",
    "properties": {
        "contributions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "contribution_type": {"type": "string"},
                    "cited_research_question_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["title", "description", "cited_research_question_ids"],
            },
        }
    },
    "required": ["contributions"],
}


def build_contribution_generation_prompt(context_json: dict[str, Any]) -> tuple[str, str]:
    system_text = (
        "You propose CANDIDATE scientific contributions that address one or more already-approved "
        "research questions for a research-management system. You are NOT assessing novelty — that "
        "is a separate step performed later by a different process. Never claim a contribution is "
        "novel, original, or unprecedented; describe only what is being proposed.\n\n"
        f"{_ANTI_HALLUCINATION_RULES}\n\n"
        "Every contribution must cite at least one of the given research_question_ids in "
        "cited_research_question_ids — a contribution that addresses none of the supplied questions "
        "is not a usable candidate."
    )
    user_text = _context_block(context_json)
    return system_text, user_text


# ==========================================================================
# methodology_generation.v1
# ==========================================================================

METHODOLOGY_GENERATION_PROMPT_NAME = "methodology_generation"
METHODOLOGY_GENERATION_PROMPT_VERSION = "v1"

METHODOLOGY_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "methodology_generation_result",
    "properties": {
        "description": {"type": "string"},
        "methodology_type": {"type": "string"},
        "components": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "reproducibility_requirements": {"type": "string"},
    },
    "required": ["description"],
}


def build_methodology_generation_prompt(context_json: dict[str, Any]) -> tuple[str, str]:
    system_text = (
        "You propose a CANDIDATE research methodology for one already-approved contribution for a "
        "research-management system. You never claim the methodology is scientifically correct, "
        "optimal, or guaranteed to work — you produce a structured proposal a human must review.\n\n"
        f"{_ANTI_HALLUCINATION_RULES}\n\n"
        "List concrete components, assumptions, and risks as short, separate strings — not one long "
        "paragraph — so a reviewer can evaluate each individually."
    )
    user_text = _context_block(context_json)
    return system_text, user_text


# ==========================================================================
# dataset_requirements_generation.v1
# ==========================================================================

DATASET_REQUIREMENTS_GENERATION_PROMPT_NAME = "dataset_requirements_generation"
DATASET_REQUIREMENTS_GENERATION_PROMPT_VERSION = "v1"

DATASET_REQUIREMENTS_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "dataset_requirements_generation_result",
    "properties": {
        "required_characteristics": {"type": "string"},
        "source_requirements": {"type": "string"},
        "inclusion_criteria": {"type": "string"},
        "exclusion_criteria": {"type": "string"},
        "annotation_requirements": {"type": "string"},
        "split_strategy": {"type": "string"},
        "leakage_considerations": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "reproducibility_requirements": {"type": "string"},
    },
    "required": ["required_characteristics"],
}


def build_dataset_requirements_generation_prompt(context_json: dict[str, Any]) -> tuple[str, str]:
    system_text = (
        "You propose CANDIDATE dataset requirements for one already-approved methodology plan for a "
        "research-management system. You describe what the research NEEDS from its data — you do not "
        "name, recommend, or assume the existence of any specific real dataset; that selection is a "
        "separate, later step.\n\n"
        f"{_ANTI_HALLUCINATION_RULES}\n\n"
        "leakage_considerations must explicitly address how train/evaluation contamination would be "
        "avoided given split_strategy."
    )
    user_text = _context_block(context_json)
    return system_text, user_text


# ==========================================================================
# experimental_design_generation.v1
# ==========================================================================

EXPERIMENTAL_DESIGN_GENERATION_PROMPT_NAME = "experimental_design_generation"
EXPERIMENTAL_DESIGN_GENERATION_PROMPT_VERSION = "v1"

EXPERIMENTAL_DESIGN_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "experimental_design_generation_result",
    "properties": {
        "proposed_method": {"type": "string"},
        "baselines": {"type": "array", "items": {"type": "string"}},
        "ablation_studies": {"type": "array", "items": {"type": "string"}},
        "evaluation_metrics": {"type": "array", "items": {"type": "string"}},
        "comparison_strategy": {"type": "string"},
        "reproducibility_requirements": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "addressed_research_question_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["proposed_method", "addressed_research_question_ids"],
}


def build_experimental_design_generation_prompt(context_json: dict[str, Any]) -> tuple[str, str]:
    system_text = (
        "You propose a CANDIDATE experimental design for one already-approved methodology plan and "
        "dataset requirements spec for a research-management system, addressing the explicitly "
        "supplied research question(s). You never claim the design guarantees valid or reproducible "
        "results — you produce a structured proposal a human must review.\n\n"
        f"{_ANTI_HALLUCINATION_RULES}\n\n"
        "addressed_research_question_ids must be a subset of the research_question_ids given in the "
        "context — never a question id you were not given."
    )
    user_text = _context_block(context_json)
    return system_text, user_text
