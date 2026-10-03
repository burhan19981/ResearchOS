"""The ResearchOS research planning layer.

Transforms human-approved research intelligence (`researchos.intelligence`,
Phase 6) into a structured, traceable research plan:

    Approved Gap -> Research Question -> Contribution Candidate
    -> Methodology Plan -> Dataset Requirements -> Experimental Design

with a hard invariant carried over from Phase 6: an LLM-generated
planning artifact never becomes authoritative merely because the LLM
produced it. Every artifact this layer persists starts at
`PlanningApprovalStatus.CANDIDATE` and requires an explicit human
decision (`researchos.planning.approval`, built on the same
`Approval`/`AuditEvent` tables `researchos.workflow` and
`researchos.intelligence` use) before a downstream generation service
will accept it as grounding for the next stage.

This package never claims a methodology is scientifically correct, a
contribution is novel, or a plan is guaranteed reproducible — it
guarantees only structural, provenance, project-scope, approval, and
evidence-traceability consistency. See
`docs/PHASE7_RESEARCH_PLANNING.md` for the full design.

This package never mutates workflow stage or literature bibliographic
facts directly, and never repurposes `NoveltyAssessment` as "the
contribution" — see `ContributionCandidate`'s own docstring in
`researchos.db.models` for why the two remain distinct.
"""

from . import approval
from .contributions import generate_contribution_candidates
from .dataset_requirements import generate_dataset_requirements
from .errors import (
    ApprovalAlreadyDecidedError,
    CandidateNotFoundError,
    CrossProjectReferenceError,
    HallucinatedPlanningReferenceError,
    HumanOnlyActionError,
    InvalidPlanningReferenceError,
    InvalidPlanningResponseError,
    InvalidPlanningStatusError,
    PlanningError,
    PlanningGenerationError,
    UnknownPlanningEntityError,
    UpstreamNotApprovedError,
)
from .experimental_design import generate_experimental_design
from .methodology import generate_methodology_plan
from .research_questions import generate_research_questions
from .types import (
    ContributionGenerationOutcome,
    DatasetRequirementsGenerationOutcome,
    ExperimentalDesignGenerationOutcome,
    MethodologyGenerationOutcome,
    PlanningContext,
    ResearchQuestionGenerationOutcome,
)

__all__ = [
    "approval",
    "generate_research_questions",
    "generate_contribution_candidates",
    "generate_methodology_plan",
    "generate_dataset_requirements",
    "generate_experimental_design",
    "PlanningContext",
    "ResearchQuestionGenerationOutcome",
    "ContributionGenerationOutcome",
    "MethodologyGenerationOutcome",
    "DatasetRequirementsGenerationOutcome",
    "ExperimentalDesignGenerationOutcome",
    "PlanningError",
    "UnknownPlanningEntityError",
    "CrossProjectReferenceError",
    "UpstreamNotApprovedError",
    "InvalidPlanningStatusError",
    "InvalidPlanningReferenceError",
    "InvalidPlanningResponseError",
    "HallucinatedPlanningReferenceError",
    "PlanningGenerationError",
    "CandidateNotFoundError",
    "ApprovalAlreadyDecidedError",
    "HumanOnlyActionError",
]
