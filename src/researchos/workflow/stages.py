"""The 20 canonical research stages and their fixed linear ordering.

This is the *only* vocabulary `ResearchProject.current_stage` may hold
(enforced entirely in this Python layer — see `docs/PHASE4_WORKFLOW.md`
for why the underlying database column, left as free text in Phase 3
specifically for this purpose, was not altered). Project-level
administrative states (paused, rejected, archived, completed) are
tracked separately via `researchos.db.models.ProjectStatus` and never
appear in `current_stage`.
"""

from __future__ import annotations

import enum
from typing import Optional


class WorkflowStage(str, enum.Enum):
    STAGE_01_IDEA = "STAGE_01_IDEA"
    STAGE_02_INITIAL_VALIDATION = "STAGE_02_INITIAL_VALIDATION"
    STAGE_03_LITERATURE_SEARCH = "STAGE_03_LITERATURE_SEARCH"
    STAGE_04_LITERATURE_MAPPING = "STAGE_04_LITERATURE_MAPPING"
    STAGE_05_RESEARCH_GAP = "STAGE_05_RESEARCH_GAP"
    STAGE_06_NOVELTY_VERIFICATION = "STAGE_06_NOVELTY_VERIFICATION"
    STAGE_07_METHODOLOGY = "STAGE_07_METHODOLOGY"
    STAGE_08_DATASET = "STAGE_08_DATASET"
    STAGE_09_EXPERIMENTAL_DESIGN = "STAGE_09_EXPERIMENTAL_DESIGN"
    STAGE_10_IMPLEMENTATION = "STAGE_10_IMPLEMENTATION"
    STAGE_11_EXPERIMENTS = "STAGE_11_EXPERIMENTS"
    STAGE_12_RESULTS_ANALYSIS = "STAGE_12_RESULTS_ANALYSIS"
    STAGE_13_SCIENTIFIC_REVIEW = "STAGE_13_SCIENTIFIC_REVIEW"
    STAGE_14_MANUSCRIPT = "STAGE_14_MANUSCRIPT"
    STAGE_15_CITATION_INTEGRITY = "STAGE_15_CITATION_INTEGRITY"
    STAGE_16_JOURNAL_SELECTION = "STAGE_16_JOURNAL_SELECTION"
    STAGE_17_SUBMISSION_PREPARATION = "STAGE_17_SUBMISSION_PREPARATION"
    STAGE_18_PEER_REVIEW = "STAGE_18_PEER_REVIEW"
    STAGE_19_REVISION = "STAGE_19_REVISION"
    STAGE_20_FINAL = "STAGE_20_FINAL"


# Canonical forward order. Index position is the single source of truth
# for what counts as "one step forward" vs. "a backward move" vs. "an
# illegal forward jump".
STAGE_ORDER: list[WorkflowStage] = [
    WorkflowStage.STAGE_01_IDEA,
    WorkflowStage.STAGE_02_INITIAL_VALIDATION,
    WorkflowStage.STAGE_03_LITERATURE_SEARCH,
    WorkflowStage.STAGE_04_LITERATURE_MAPPING,
    WorkflowStage.STAGE_05_RESEARCH_GAP,
    WorkflowStage.STAGE_06_NOVELTY_VERIFICATION,
    WorkflowStage.STAGE_07_METHODOLOGY,
    WorkflowStage.STAGE_08_DATASET,
    WorkflowStage.STAGE_09_EXPERIMENTAL_DESIGN,
    WorkflowStage.STAGE_10_IMPLEMENTATION,
    WorkflowStage.STAGE_11_EXPERIMENTS,
    WorkflowStage.STAGE_12_RESULTS_ANALYSIS,
    WorkflowStage.STAGE_13_SCIENTIFIC_REVIEW,
    WorkflowStage.STAGE_14_MANUSCRIPT,
    WorkflowStage.STAGE_15_CITATION_INTEGRITY,
    WorkflowStage.STAGE_16_JOURNAL_SELECTION,
    WorkflowStage.STAGE_17_SUBMISSION_PREPARATION,
    WorkflowStage.STAGE_18_PEER_REVIEW,
    WorkflowStage.STAGE_19_REVISION,
    WorkflowStage.STAGE_20_FINAL,
]

STAGE_INDEX: dict[WorkflowStage, int] = {stage: index for index, stage in enumerate(STAGE_ORDER)}

INITIAL_STAGE: WorkflowStage = STAGE_ORDER[0]


def next_stage(stage: WorkflowStage) -> Optional[WorkflowStage]:
    """The single canonical next stage, or None if `stage` is the last one."""
    index = STAGE_INDEX[stage]
    return STAGE_ORDER[index + 1] if index + 1 < len(STAGE_ORDER) else None


def is_forward_step(from_stage: WorkflowStage, to_stage: WorkflowStage) -> bool:
    """True iff `to_stage` is exactly one canonical step ahead of `from_stage`."""
    return STAGE_INDEX[to_stage] == STAGE_INDEX[from_stage] + 1


def is_backward(from_stage: WorkflowStage, to_stage: WorkflowStage) -> bool:
    """True iff `to_stage` is any earlier stage than `from_stage`."""
    return STAGE_INDEX[to_stage] < STAGE_INDEX[from_stage]


def earlier_stages(stage: WorkflowStage) -> list[WorkflowStage]:
    """All canonical stages strictly before `stage`, in forward order."""
    return STAGE_ORDER[: STAGE_INDEX[stage]]
