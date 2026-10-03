"""Normalized error hierarchy for the research intelligence layer.

Self-contained, like every other phase's `errors.py` — nothing here
imports from `researchos.llm.errors` (an `LLMError` raised by the
provider layer during a generation call is allowed to propagate
unchanged; it is already normalized). These errors describe
intelligence-layer-specific rule violations: an LLM response that
references evidence outside what it was given, an evidence package
that can't be built, or an approval-flow misuse.
"""

from __future__ import annotations


class IntelligenceError(Exception):
    """Base class for all normalized research-intelligence-layer errors."""


class EvidencePackageError(IntelligenceError):
    """Could not build a valid evidence package (e.g. no literature items resolved)."""


class InvalidAnalysisResponseError(IntelligenceError):
    """The LLM's structured response did not match the expected shape."""


class HallucinatedEvidenceReferenceError(IntelligenceError):
    """The LLM referenced a LiteratureItem id that was not in the evidence
    package it was given — the core anti-hallucination guard. Never
    silently accepted; the offending claim/candidate is rejected."""


class CandidateNotFoundError(IntelligenceError):
    """No AnalysisClaim / ResearchGap / NoveltyAssessment with the given id."""


class ApprovalRequiredError(IntelligenceError):
    """An attempt was made to treat a candidate as approved without going
    through `researchos.intelligence.approval`."""


class ApprovalAlreadyDecidedError(IntelligenceError):
    """The candidate's approval has already been decided."""


class HumanOnlyActionError(IntelligenceError):
    """An agent actor attempted an action reserved for a human — approving,
    rejecting, or requesting changes on a candidate is always a human act,
    exactly as in `researchos.workflow`; the LLM cannot approve its own output."""
