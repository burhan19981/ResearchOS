"""Deterministic transition policy: AUTO_ALLOWED / APPROVAL_REQUIRED / HUMAN_ONLY.

This module contains no I/O and calls no LLM — it is pure, deterministic
Python, exactly so it can be exhaustively unit tested and so nothing
about "does this need approval" is ever decided by a model. See
`docs/PHASE4_WORKFLOW.md` for the rationale behind each gate.
"""

from __future__ import annotations

import enum

from .errors import InvalidTransitionError
from .stages import WorkflowStage, is_backward, is_forward_step


class Policy(str, enum.Enum):
    AUTO_ALLOWED = "auto_allowed"
    APPROVAL_REQUIRED = "approval_required"
    HUMAN_ONLY = "human_only"


# Policy for each of the 19 canonical forward edges, keyed by the
# destination stage (a forward edge is fully identified by its
# destination, since there is exactly one canonical predecessor).
#
# Mapping back to the Phase 4 spec's 11 named approval gates:
#   1. Accepting the idea as the active direction  -> STAGE_02 (APPROVAL_REQUIRED)
#   2. Accepting a proposed research gap            -> STAGE_06 (APPROVAL_REQUIRED)
#   3. Accepting a novelty claim                     -> STAGE_07 (APPROVAL_REQUIRED)
#   4. Approving the methodology                     -> STAGE_08 (APPROVAL_REQUIRED)
#   5. Approving dataset/split decisions              -> STAGE_09 (APPROVAL_REQUIRED)
#   6. Launching expensive experiments                 -> STAGE_11 (APPROVAL_REQUIRED)
#   7. Approving major manuscript changes               -> STAGE_15 (APPROVAL_REQUIRED)
#   8. Selecting the target journal                      -> STAGE_17 (APPROVAL_REQUIRED)
#   9. Preparing final submission                         -> STAGE_18 (APPROVAL_REQUIRED)
#  10. Responding to peer reviewers with a final response \
#  11. Moving to final/publication status                 } -> STAGE_20 (HUMAN_ONLY)
#
# Gates 10 and 11 are the same real-world moment in this stage-level
# model (there is no separate "action" layer below a stage in Phase 4),
# so both are represented by the single HUMAN_ONLY gate on STAGE_20.
FORWARD_GATE_POLICY: dict[WorkflowStage, Policy] = {
    WorkflowStage.STAGE_02_INITIAL_VALIDATION: Policy.APPROVAL_REQUIRED,
    WorkflowStage.STAGE_03_LITERATURE_SEARCH: Policy.AUTO_ALLOWED,
    WorkflowStage.STAGE_04_LITERATURE_MAPPING: Policy.AUTO_ALLOWED,
    WorkflowStage.STAGE_05_RESEARCH_GAP: Policy.AUTO_ALLOWED,
    WorkflowStage.STAGE_06_NOVELTY_VERIFICATION: Policy.APPROVAL_REQUIRED,
    WorkflowStage.STAGE_07_METHODOLOGY: Policy.APPROVAL_REQUIRED,
    WorkflowStage.STAGE_08_DATASET: Policy.APPROVAL_REQUIRED,
    WorkflowStage.STAGE_09_EXPERIMENTAL_DESIGN: Policy.APPROVAL_REQUIRED,
    WorkflowStage.STAGE_10_IMPLEMENTATION: Policy.AUTO_ALLOWED,
    WorkflowStage.STAGE_11_EXPERIMENTS: Policy.APPROVAL_REQUIRED,
    WorkflowStage.STAGE_12_RESULTS_ANALYSIS: Policy.AUTO_ALLOWED,
    WorkflowStage.STAGE_13_SCIENTIFIC_REVIEW: Policy.AUTO_ALLOWED,
    WorkflowStage.STAGE_14_MANUSCRIPT: Policy.AUTO_ALLOWED,
    WorkflowStage.STAGE_15_CITATION_INTEGRITY: Policy.APPROVAL_REQUIRED,
    WorkflowStage.STAGE_16_JOURNAL_SELECTION: Policy.AUTO_ALLOWED,
    WorkflowStage.STAGE_17_SUBMISSION_PREPARATION: Policy.APPROVAL_REQUIRED,
    WorkflowStage.STAGE_18_PEER_REVIEW: Policy.APPROVAL_REQUIRED,
    WorkflowStage.STAGE_19_REVISION: Policy.AUTO_ALLOWED,
    WorkflowStage.STAGE_20_FINAL: Policy.HUMAN_ONLY,
}

# Every backward move (to any earlier canonical stage) always requires
# approval, regardless of which specific stages are involved. This is a
# deliberate simplification over hand-curating "scientifically valid"
# backward pairs (see docs/PHASE4_WORKFLOW.md): forward jumps of more
# than one step are never allowed at all, so the only remaining
# question for a backward move is "is it justified", which is exactly
# what an approval with a recorded reason is for.
BACKWARD_POLICY = Policy.APPROVAL_REQUIRED

# Fixed policy for project-level administrative actions (not part of the
# stage graph). Pausing/resuming are treated as low-risk and reversible;
# archiving/rejecting a project's overall direction is treated as
# consequential enough to require human sign-off.
PAUSE_POLICY = Policy.AUTO_ALLOWED
RESUME_POLICY = Policy.AUTO_ALLOWED
ARCHIVE_POLICY = Policy.APPROVAL_REQUIRED
REJECT_POLICY = Policy.APPROVAL_REQUIRED


def get_policy(from_stage: WorkflowStage, to_stage: WorkflowStage) -> Policy:
    """Return the policy tier governing a move from `from_stage` to `to_stage`.

    Raises `InvalidTransitionError` for a no-op (`from_stage == to_stage`)
    or an illegal forward jump (skipping one or more canonical stages).
    """
    if from_stage == to_stage:
        raise InvalidTransitionError(f"Target stage {to_stage.value} is the same as the current stage.")
    if is_forward_step(from_stage, to_stage):
        return FORWARD_GATE_POLICY[to_stage]
    if is_backward(from_stage, to_stage):
        return BACKWARD_POLICY
    raise InvalidTransitionError(
        f"Cannot move from {from_stage.value} directly to {to_stage.value}: forward progress "
        "must advance exactly one canonical stage at a time (no skipping stages)."
    )


# --------------------------------------------------------------------------
# Actor convention
# --------------------------------------------------------------------------
#
# ResearchOS has no real identity/authentication system yet (that is a
# future phase). Until one exists, this module uses a simple, explicit,
# testable placeholder convention: an actor string prefixed with
# "agent:" is agent-originated; every other actor string (e.g.
# "system", "user:alice", "human:bob") is treated as human-originated.
# This convention is deliberately documented rather than hidden, since
# it is the single most important fact a future auth-integration phase
# needs to know to replace it correctly.

_AGENT_ACTOR_PREFIX = "agent:"


def is_human_actor(actor: str) -> bool:
    """Whether `actor` should be treated as a human for policy purposes.

    See the actor-convention note above — this is a placeholder rule,
    not a real identity check.
    """
    return not actor.strip().lower().startswith(_AGENT_ACTOR_PREFIX)
