"""Normalized error hierarchy for the research planning layer.

Self-contained, like every other phase's `errors.py` — nothing here
imports from `researchos.intelligence.errors` or `researchos.llm.errors`
(an `LLMError` raised by the provider layer during a generation call is
allowed to propagate unchanged; it is already normalized). These errors
describe planning-layer-specific rule violations: an unknown/cross-
project upstream reference, an upstream artifact that isn't approved
yet, or a generated response that references something outside its
context package.
"""

from __future__ import annotations


class PlanningError(Exception):
    """Base class for all normalized research-planning-layer errors."""


class UnknownPlanningEntityError(PlanningError):
    """No entity of the expected type exists with the given id."""


class CrossProjectReferenceError(PlanningError):
    """An entity exists but belongs to a different project than the one
    the caller supplied — never silently mixed across projects."""


class UpstreamNotApprovedError(PlanningError):
    """An upstream artifact exists and is in the right project, but its
    `planning_status` (or Phase 6 equivalent) is not the approved value —
    only an APPROVED/VALIDATED upstream artifact may ground downstream
    generation."""


class InvalidPlanningStatusError(PlanningError):
    """A caller or response attempted to set a planning_status value this
    layer does not allow through this path (e.g. an LLM response
    claiming APPROVED)."""


class InvalidPlanningReferenceError(PlanningError):
    """A caller-supplied reference is structurally inconsistent — e.g. a
    research_question_id not actually linked to the contribution being
    used, or a dataset requirements row that belongs to a different
    methodology plan than the one supplied alongside it."""


class InvalidPlanningResponseError(PlanningError):
    """The LLM's structured response did not match the expected shape."""


class HallucinatedPlanningReferenceError(PlanningError):
    """The LLM referenced an id that was not in the context package it
    was given — the anti-hallucination guard. Never silently accepted;
    the offending entry is rejected."""


class PlanningGenerationError(PlanningError):
    """A planning generation call could not produce a usable result
    (distinct from an `LLMError`, which is allowed to propagate
    unchanged — this covers planning-layer-specific generation failures)."""


class CandidateNotFoundError(PlanningError):
    """No planning candidate entity exists with the given id — the
    not-found error type used by `researchos.planning.approval` via
    `researchos.db.approval_dispatch`."""


class ApprovalAlreadyDecidedError(PlanningError):
    """The candidate's approval has already been decided."""


class HumanOnlyActionError(PlanningError):
    """An agent actor attempted an action reserved for a human — approving,
    rejecting, or requesting changes on a planning candidate is always a
    human act; the LLM can never approve its own output."""
