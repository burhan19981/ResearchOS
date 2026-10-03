"""The ResearchOS analysis & scientific review layer (Phase 8).

Implements the pipeline Phase 8's spec is built around:

    Experiment -> Run -> Artifacts + Metrics
    -> Analysis (deterministic computation, LEVEL 2)
    -> Comparison / Comparability
    -> Candidate Scientific Claim (interpretation, LEVEL 3)
    -> Scientific Review (evidence-adequacy assessment)
    -> Human Approval
    -> Approved Research Knowledge (LEVEL 4 — never system-declared)

Four levels are never collapsed into each other:

- LEVEL 1 OBSERVATION — what a `Run`/`Metric`/`ArtifactMetadata`
  already recorded (Phase 8B-1/8B-2/8B-3's domain, untouched here).
- LEVEL 2 COMPUTATION — a deterministic calculation over those
  observations (`researchos.analysis.numeric`/`comparability`/
  `records`), persisted as an immutable `AnalysisRecord`. The system
  may fully automate this level.
- LEVEL 3 INTERPRETATION — what the evidence may suggest
  (`researchos.analysis.claims`/`reviews`), always a `CANDIDATE`
  `ScientificClaim`/`ScientificReview`. The system may assist here,
  via the existing provider-neutral LLM abstraction, but every
  generated interpretation is advisory and traceable to explicit
  supporting `AnalysisRecord` ids — never a hallucinated reference.
- LEVEL 4 SCIENTIFIC CONCLUSION — what a human researcher ultimately
  accepts (`researchos.analysis.approval`). Only a human actor may ever
  move a `ScientificReview` to `HUMAN_APPROVED` or a `ScientificClaim`
  to `APPROVED`; an LLM can never approve its own output, and a claim
  can never be approved without a `HUMAN_APPROVED` review behind it.

"Run succeeded" is never turned into "the method is effective."
"Metric A > Metric B" is never turned into "Method A is scientifically
superior." A purely mathematical ranking
(`researchos.analysis.numeric.rank_values`/`records.rank_runs`) never
produces a semantic `BEST_MODEL`/`WINNER` entity or label.

Domain-neutral throughout: nothing in this package contains PPE/
FastViT/RetinaNet/YOLO/PyTorch-specific logic, and no accuracy/
precision/recall/F1/mAP/IoU metric name is ever hard-coded as a special
case — `Metric.name` is free text, exactly as Phase 8B-2 established.

Reuses rather than duplicates: `researchos.planning.orchestration` for
existence/project checks, `researchos.planning.errors`' generic
reference-checking types (via this package's own `errors.py`
re-export, matching `researchos.execution.errors`' precedent),
`researchos.db.approval_dispatch` for human-approval mechanics, and
`EvidenceLink`/`EvidenceSubjectType` (extended with `SCIENTIFIC_CLAIM`/
`ANALYSIS_RECORD`) for literature-based evidence toward these new
entities. See docs/PHASE8_ANALYSIS_SCIENTIFIC_REVIEW.md for the full
design.
"""

from . import approval
from .claims import create_scientific_claim, generate_candidate_claim
from .comparability import check_comparability, resolve_unique_metric
from .errors import (
    AnalysisError,
    ApprovalAlreadyDecidedError,
    CandidateNotFoundError,
    ClaimNotSupportedByApprovedReviewError,
    CrossProjectReferenceError,
    HumanOnlyActionError,
    InsufficientObservationsError,
    InvalidAnalysisInputError,
    InvalidAnalysisResponseError,
    MissingEntityError,
    NumericSafetyError,
    ReviewNotReadyError,
    UnknownEvidenceReferenceError,
    UpstreamNotApprovedError,
)
from .records import aggregate_runs, compare_runs, rank_runs
from .reviews import create_scientific_review, generate_scientific_review
from .types import (
    AnalysisContext,
    ClaimGenerationOutcome,
    ComparabilityResult,
    ReviewContext,
    ReviewGenerationOutcome,
)

__all__ = [
    "approval",
    "compare_runs",
    "aggregate_runs",
    "rank_runs",
    "check_comparability",
    "resolve_unique_metric",
    "create_scientific_claim",
    "generate_candidate_claim",
    "create_scientific_review",
    "generate_scientific_review",
    "AnalysisContext",
    "ComparabilityResult",
    "ReviewContext",
    "ClaimGenerationOutcome",
    "ReviewGenerationOutcome",
    "AnalysisError",
    "MissingEntityError",
    "CrossProjectReferenceError",
    "UpstreamNotApprovedError",
    "NumericSafetyError",
    "InsufficientObservationsError",
    "InvalidAnalysisInputError",
    "InvalidAnalysisResponseError",
    "ReviewNotReadyError",
    "ClaimNotSupportedByApprovedReviewError",
    "UnknownEvidenceReferenceError",
    "CandidateNotFoundError",
    "ApprovalAlreadyDecidedError",
    "HumanOnlyActionError",
]
