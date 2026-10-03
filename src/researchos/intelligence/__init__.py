"""The ResearchOS research intelligence layer.

Turns persisted, provenance-carrying evidence (`researchos.evidence`)
into LLM-assisted analysis — literature dimension analysis, candidate
research gaps, and candidate novelty assessments — through the
provider-agnostic LLM layer (`researchos.llm`), with a hard invariant:

    LLM output -> candidate -> evidence verification -> human approval -> approved knowledge

An LLM-generated statement never becomes an authoritative research fact
merely because the LLM produced it. Every claim/gap/novelty-comparison
this layer persists must trace back to specific `LiteratureItem`
evidence (see `researchos.intelligence.response_validation` for the
anti-hallucination guard), and every candidate requires an explicit
human decision (`researchos.intelligence.approval`, built on the same
`Approval`/`AuditEvent` tables `researchos.workflow` uses) before it
means anything more than "an LLM noticed a pattern worth reviewing."

This package never mutates workflow stage, literature bibliographic
facts, or project state directly — those remain the exclusive authority
of `researchos.workflow` and `researchos.evidence` respectively. See
`docs/PHASE6_RESEARCH_INTELLIGENCE.md` for the full design.
"""

from . import approval
from .errors import (
    ApprovalAlreadyDecidedError,
    ApprovalRequiredError,
    CandidateNotFoundError,
    EvidencePackageError,
    HallucinatedEvidenceReferenceError,
    HumanOnlyActionError,
    IntelligenceError,
    InvalidAnalysisResponseError,
)
from .evidence_package import build_evidence_package
from .gap_analysis import generate_gap_candidates
from .literature_analysis import run_literature_analysis
from .novelty_analysis import analyze_novelty_candidate
from .types import (
    ANALYSIS_DIMENSIONS,
    EvidencePackage,
    EvidencePackageItem,
    GapCandidateOutcome,
    LiteratureAnalysisOutcome,
    NoveltyAnalysisOutcome,
)

__all__ = [
    "approval",
    "build_evidence_package",
    "run_literature_analysis",
    "generate_gap_candidates",
    "analyze_novelty_candidate",
    "ANALYSIS_DIMENSIONS",
    "EvidencePackage",
    "EvidencePackageItem",
    "LiteratureAnalysisOutcome",
    "GapCandidateOutcome",
    "NoveltyAnalysisOutcome",
    "IntelligenceError",
    "EvidencePackageError",
    "InvalidAnalysisResponseError",
    "HallucinatedEvidenceReferenceError",
    "CandidateNotFoundError",
    "ApprovalRequiredError",
    "ApprovalAlreadyDecidedError",
    "HumanOnlyActionError",
]
