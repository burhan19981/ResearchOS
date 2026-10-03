"""Versioned prompt template + JSON schema for `ExperimentSpecification`
generation: `experiment_specification_generation.v1`.

No API key or secret is ever interpolated into a prompt. No schema
field offers `planning_status`/approval — the generation service always
hard-codes `PlanningApprovalStatus.CANDIDATE` when persisting,
regardless of what a response contains.
"""

from __future__ import annotations

import json
from typing import Any

EXPERIMENT_SPECIFICATION_GENERATION_PROMPT_NAME = "experiment_specification_generation"
EXPERIMENT_SPECIFICATION_GENERATION_PROMPT_VERSION = "v1"

_ANTI_HALLUCINATION_RULES = """
STRICT RULES — violating any of these makes your response invalid:
1. You may ONLY reference ids that appear in the CONTEXT JSON below.
   Never invent, guess, or reuse an id from outside it.
2. Never invent a dataset fact, citation, or result that is not present
   in the supplied context.
3. Everything you produce is a CANDIDATE for human review — never
   approved, never a guarantee of correct, optimal, or reproducible
   results. Never claim this configuration is scientifically optimal.
4. Respond with JSON only, matching the provided schema exactly. Do not
   include any status/approval field even if you believe one is
   warranted — approval is exclusively a human decision made outside
   this response.
5. `configuration` must be a plain, domain-agnostic JSON object — do not
   assume a specific ML framework or hardcode fields that only make
   sense for one research domain unless the supplied design/methodology
   explicitly calls for them.
""".strip()

EXPERIMENT_SPECIFICATION_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "experiment_specification_generation_result",
    "properties": {
        "description": {"type": "string"},
        "configuration": {"type": "object"},
        "baselines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "version": {"type": "string"},
                    "source": {"type": "string"},
                    "implementation_reference": {"type": "string"},
                    "configuration": {"type": "object"},
                    "rationale": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "addressed_research_question_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["description", "configuration", "addressed_research_question_ids"],
}


def build_experiment_specification_generation_prompt(context_json: dict[str, Any]) -> tuple[str, str]:
    """Returns (system_text, user_text) for an
    experiment_specification_generation.v1 call."""
    system_text = (
        "You propose a CANDIDATE, execution-ready experiment specification implementing one "
        "already-approved experimental design against one already-approved dataset version, for a "
        "research-management system. You never claim this configuration will produce correct, "
        "optimal, or reproducible results — you produce a structured proposal a human must review. "
        "You never execute anything and never describe yourself as executing anything.\n\n"
        f"{_ANTI_HALLUCINATION_RULES}\n\n"
        "addressed_research_question_ids must be a non-empty subset of the research_question_ids "
        "given in the context. Each baseline, if any, should be a named, structured comparison point "
        "— never invent a specific real baseline result; describe only what would be compared."
    )
    user_text = "CONTEXT JSON (the only prior content/ids you may reference):\n" + json.dumps(context_json, indent=2)
    return system_text, user_text
