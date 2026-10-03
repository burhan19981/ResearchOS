> Historical implementation notes. For current setup, status, and security boundaries, see [the README](../README.md) and [SECURITY.md](../SECURITY.md). Historical test counts describe earlier development checkpoints.

# Phase 8: Analysis & Scientific Review

Date: 2026-09-18
Scope: a domain-neutral analysis and scientific review layer
(`researchos.analysis`) implementing the pipeline `Experiment -> Run ->
Artifacts + Metrics -> Analysis -> Comparison -> Scientific
Interpretation -> Scientific Review -> Research Knowledge`. This phase
adds one new package, five new tables, two new `EvidenceSubjectType`
members, and zero changes to any Phase 8B-1/8B-2/8B-3 execution
machinery. **No real LLM API call was made anywhere in this phase's
implementation or test suite** — every LLM-assisted service function is
exercised only against an injected `FakeLLMProvider`.

## The Four-Level Model

Every function in this package is anchored to exactly one of four
levels, and nothing here ever collapses one level into another:

| Level | Name | What it is | Who/what produces it |
|---|---|---|---|
| 1 | OBSERVATION | What a `Run`/`Metric`/`ArtifactMetadata` already recorded | Phase 8B-1/8B-2/8B-3 (untouched by this phase) |
| 2 | COMPUTATION | A deterministic calculation over observations | `researchos.analysis.numeric`/`comparability`/`records` — fully automatable |
| 3 | INTERPRETATION | What the evidence *may suggest* | `researchos.analysis.claims`/`reviews` — system-assisted, always `CANDIDATE` |
| 4 | SCIENTIFIC CONCLUSION | What a researcher ultimately accepts | `researchos.analysis.approval` — human-only |

Worked example from the spec, traced through the actual code:

1. **RAW FACT** (Level 1): `Metric(run_id=17, name="f1", value=0.842)`
   — already existed before this phase, untouched.
2. **DERIVED FACT** (Level 2): `compare_runs(project_id, 12, 17, "f1",
   ...)` computes `absolute_difference = 0.842 - 0.811 = 0.031` and
   persists it as an immutable `AnalysisRecord`. This is pure
   arithmetic — `researchos.analysis.numeric` has no concept of "good"
   or "bad."
3. **INTERPRETATION** (Level 3): `generate_candidate_claim(project_id,
   [analysis_record_id], ...)` may propose a `ScientificClaim` such as
   "Run 17's F1 may be higher than Run 12's under these conditions" —
   always `approval_status=PENDING_REVIEW`, always hedged language,
   always traceable to the exact `AnalysisRecord` it rests on.
4. **SCIENTIFIC CONCLUSION** (Level 4): only
   `researchos.analysis.approval.approve_scientific_claim`, called by a
   human actor, after at least one linked `ScientificReview` is itself
   `HUMAN_APPROVED`, can ever move that claim to `APPROVED`.

"Run succeeded" is never turned into "the method is effective." "Metric
A > Metric B" is never turned into "Method A is scientifically
superior." Nowhere in this package does a persisted result contain the
words "best," "winner," "better," or "worse" as a system-declared
verdict — `researchos.analysis.numeric.rank_values` produces a purely
mathematical ordering (`{"index", "value", "rank"}`), never a semantic
`BEST_MODEL`/`WINNER` entity.

## Architecture

```
Run + Metric (Phase 8B-1/8B-2, unchanged)
        │
        ▼
check_comparability()          researchos.analysis.comparability
        │  same DatasetVersion id, same dataset fingerprint,
        │  unambiguous metric resolution, same unit, same split
        ▼
compare_runs() / aggregate_runs() / rank_runs()   researchos.analysis.records
        │  calls researchos.analysis.numeric (pure math, stdlib only)
        ▼
AnalysisRecord (COMPLETED or NOT_COMPARABLE) + AnalysisInput edges
        │
        ▼
create_scientific_claim() / generate_candidate_claim()   researchos.analysis.claims
        │  manual, or LLM-assisted via researchos.analysis.context/
        │  llm_call/validation/prompts — always PENDING_REVIEW
        ▼
ScientificClaim  <──ScientificClaimAnalysis──  AnalysisRecord(s)
        │
        ▼
create_scientific_review() / generate_scientific_review()   researchos.analysis.reviews
        │  12-dimension structured assessment; LLM may only propose
        │  DRAFT/CANDIDATE/NEEDS_MORE_EVIDENCE/READY_FOR_HUMAN_REVIEW
        ▼
ScientificReview
        │
        ▼
researchos.analysis.approval    (human actor only; approval_dispatch)
        │  approve_scientific_review requires READY_FOR_HUMAN_REVIEW
        │  approve_scientific_claim requires a HUMAN_APPROVED review
        ▼
Approved Research Knowledge   <- a human decision, never system-declared
```

## The Analysis Layer

`researchos.analysis.numeric` is the pure, dependency-free deterministic
core: no I/O, no database, no randomness, Python stdlib `statistics`
only (no `numpy`/`scipy` dependency exists in `pyproject.toml`, and none
was added). It implements absolute/relative/percentage difference,
paired comparison, mean/median/min/max/range/standard-deviation/
variance, a pure-ordering `rank_values`, and `aggregate_repeated_runs`.
Every function rejects NaN/Infinity/non-numeric/empty/
insufficient-observation input via typed `NumericSafetyError`/
`InsufficientObservationsError` — never silently coercing an invalid
value into a plausible-looking number, and never fabricating a standard
deviation for a single observation (`None`, not `0.0`).

`researchos.analysis.records` is the only place `numeric.py`'s
functions are called against real `Run`/`Metric` data and persisted:

- `compare_runs(project_id, baseline_run_id, comparison_run_id,
  metric_name, ...)` — calls `check_comparability` first. If not
  comparable, it still persists an `AnalysisRecord`
  (`status=NOT_COMPARABLE`, `result={"comparable": False, "reasons":
  [...]}`) — a comparability finding is itself a valid, reproducible
  computed fact, never a silent failure. If comparable, it persists
  `absolute_difference`/`relative_difference`/`percentage_change`
  (the latter two omitted, not fabricated, when the baseline is zero).
- `aggregate_runs(project_id, run_ids, metric_name, ...)` — repeated-run
  aggregation. Every `run_id` is explicit; there is no "latest N runs"
  inference anywhere in this package. Does **not** run the full
  pairwise `check_comparability` (dataset-version/fingerprint/unit
  checks) — aggregation assumes repeated measurements of the *same*
  condition by construction, a different scenario from comparing
  genuinely different conditions.
- `rank_runs(project_id, run_ids, metric_name, ...)` — a purely
  mathematical ordering, never a verdict.

Every one of these three functions links `AnalysisInput` rows for every
`Run`/`Metric` it actually used (mirroring `EvidenceLink.subject_id`'s
established polymorphic-by-convention pattern — no cross-table database
FK is possible, so the repository layer validates existence + project
ownership before inserting) and appends an `AuditEvent`
(`analysis.comparison_created`/`analysis.comparison_not_comparable`/
`analysis.analysis_completed`).

## Comparability

`researchos.analysis.comparability.check_comparability` never guesses.
Two Runs sharing a metric name are not comparable merely because of
that — it checks: same project (a genuine caller error, raised via
`CrossProjectReferenceError`, not returned as a finding), same
`DatasetVersion` id, same dataset content fingerprint, the metric exists
*unambiguously* on both Runs (an ambiguous match across multiple splits
with no `split=` given is treated as a structured reason, not silently
resolved), and the two resolved metrics share the same unit and split.
`resolve_unique_metric` — the ambiguity-resolution helper — is public
specifically so `records.py`'s `aggregate_runs`/`rank_runs` can reuse
the exact same logic rather than duplicating it.

If comparability cannot be established, the result is
`ComparabilityResult(comparable=False, reasons=[...])` — every reason a
human-readable, specific string. The system never guesses.

## Statistics: Descriptive, Never Inferential

This phase implements only descriptive statistics (mean, median,
standard deviation, variance, range) via Python's stdlib `statistics`
module. **No inferential statistics** — no hypothesis tests, no
p-values, no confidence intervals — are implemented. This is a
deliberate scope boundary, not an oversight: a half-implemented
significance claim (or one silently smuggled in via an unvalidated
third-party statistics library) is worse than none, and the spec's own
requirement — that any future significance claim must explicitly carry
its test/assumptions/sample-size/alpha/test-statistic/p-value/effect-size
— is trivially satisfied by not claiming significance at all yet. A
future phase that adds inferential statistics should add it as new,
explicitly-labeled functions in `numeric.py`, never retrofitted onto the
descriptive ones.

## Scientific Review

A `ScientificReview` is **not** a code review, not an execution review,
and not a re-check of any metric's arithmetic — it assesses whether the
evidence *already computed* adequately supports one `ScientificClaim`.
Its `dimensions` column holds a structured, twelve-key JSON assessment
(evidence completeness, experimental consistency, dataset consistency,
metric appropriateness, baseline adequacy, ablation coverage,
reproducibility, statistical support, threats to validity, claim
strength, alternative explanations, missing evidence) — matching this
codebase's established "structured scientific content as validated
JSON, not one column per field" convention
(`MethodologyPlan`/`ExperimentalDesign`).

`ScientificReviewStatus` (`DRAFT` / `CANDIDATE` / `NEEDS_MORE_EVIDENCE`
/ `READY_FOR_HUMAN_REVIEW` / `HUMAN_APPROVED` / `REJECTED`) is
deliberately distinct from `ClaimStrength` (the *outcome* a review's
dimensions assess) and from `ClaimApprovalStatus` (the claim's own
separate human decision). Both `researchos.analysis.reviews.
create_scientific_review` (manual) and `generate_scientific_review`
(LLM-assisted) refuse to ever persist `HUMAN_APPROVED` or `REJECTED` —
the manual path raises `InvalidAnalysisInputError` if a caller tries,
and the LLM path raises `InvalidAnalysisResponseError` (nothing
persisted, the failure audited) if the model's structured response ever
proposes either value.

## Claim Lifecycle

A `ScientificClaim` is a candidate interpretive statement — distinct
from Phase 6's `AnalysisClaim` (a *literature-synthesis* claim tied to
one `LiteratureAnalysis` run). This is an *experimental-evidence* claim
tied to `AnalysisRecord`/`Run`/`Metric` evidence via
`ScientificClaimAnalysis`. It reuses Phase 6's `ClaimApprovalStatus`
directly (`PENDING_REVIEW` / `APPROVED` / `REJECTED` /
`CHANGES_REQUESTED`) — the same candidate-to-human-decision shape
`AnalysisClaim.approval_status` already established, a better semantic
fit than reusing a "planning artifact" vocabulary for a claim.

`ClaimStrength` (`SUPPORTED` / `PARTIALLY_SUPPORTED` /
`INSUFFICIENT_EVIDENCE` / `CONTRADICTED` / `NOT_ASSESSABLE`) is a
distinctly-named, richer vocabulary from Phase 6's `ClaimSupportLevel`
— an evidence-assessment outcome, never a declaration of universal
truth. `NOT_ASSESSABLE` is the default; it is set only by an actual
assessment, never assumed to mean "true until proven otherwise."

Both `create_scientific_claim` (manual) and `generate_candidate_claim`
(LLM-assisted) always persist `approval_status=PENDING_REVIEW`. Neither
ever sets `APPROVED` — that responsibility belongs exclusively to
`researchos.analysis.approval.approve_scientific_claim`, and only after
at least one linked `ScientificReview` is `HUMAN_APPROVED`
(`ClaimNotSupportedByApprovedReviewError` otherwise — there is no path
to an approved claim that skips review entirely). Both `ScientificClaim`
and `ScientificReview` are versioned exactly like `AnalysisRecord`/
`DatasetVersion`: a claim or review revised in light of new evidence is
a new row, `supersedes_id` pointing at the one it refines, protected by
a `UniqueConstraint` enforcing an unbranching lineage — the same pattern
Phase 7/8A/8B-3 established. `researchos.db.repository` deliberately
exposes no `update_analysis_record`/`update_scientific_claim`-as-mutation
path for content fields — immutability by construction.

## Evidence Linkage

Two distinct mechanisms, each reused for its actual intended purpose
rather than one being stretched to cover both:

- **`AnalysisInput`** (new) — which `Run`/`Metric`/`ArtifactMetadata`
  rows a computed `AnalysisRecord` actually used. Polymorphic by
  convention (`input_type` + `input_id`), mirroring `EvidenceLink.
  subject_id`'s established shape.
- **`ScientificClaimAnalysis`** (new) — which `AnalysisRecord`(s) a
  `ScientificClaim` actually rests on. A plain association table (own
  `project_id`, two `CASCADE` FKs, a `UniqueConstraint` on the pair),
  the same shape `ContributionCandidateQuestion`/
  `ExperimentSpecificationQuestion` already established.
- **`EvidenceLink`** (Phase 6, extended) — `EvidenceSubjectType` gained
  `SCIENTIFIC_CLAIM` and `ANALYSIS_RECORD` so genuine *literature-based*
  evidence can still be linked toward these new entities through the
  existing mechanism, without altering `EvidenceLink`'s own required
  `literature_item_id` FK (which structurally cannot represent a
  Run/Metric/AnalysisRecord "supporting" a claim — the reason
  `AnalysisInput`/`ScientificClaimAnalysis` exist as separate,
  non-polymorphic-toward-literature mechanisms).

The full traceability chain a `ScientificClaim` sits at the end of:
`Run -> Metric/Artifact (AnalysisInput) -> AnalysisRecord ->
(ScientificClaimAnalysis) -> ScientificClaim -> ScientificReview ->
Human Approval -> Approved Research Knowledge`.

## Human Approval

`researchos.analysis.approval` reuses the Phase 4
`Approval`/`AuditEvent`/`ApprovalDecision` tables and
`researchos.workflow.policy.is_human_actor` through the shared
`researchos.db.approval_dispatch` mechanics — the same generic
dispatcher `researchos.intelligence.approval`/`researchos.planning.
approval` use. No parallel approval system exists here either. Two new
gate types: `SCIENTIFIC_REVIEW_APPROVAL:<id>` and
`SCIENTIFIC_CLAIM_APPROVAL:<id>`, each with an extra precondition beyond
ordinary approval-dispatch mechanics (checked *before* any
`Approval`/`AuditEvent` row is touched):

- `approve_scientific_review` requires `status ==
  READY_FOR_HUMAN_REVIEW` (`ReviewNotReadyError` otherwise).
- `approve_scientific_claim` requires at least one linked
  `ScientificReview` to already be `HUMAN_APPROVED`
  (`ClaimNotSupportedByApprovedReviewError` otherwise).

Every decision function requires a human actor
(`researchos.workflow.policy.is_human_actor`, the `"agent:"`-prefix
convention) and raises `HumanOnlyActionError` immediately for an agent
actor — the LLM can never approve its own output, exactly as every
prior phase's approval gate enforces. "Changes requested" for a review
naturally maps onto that lifecycle's own `NEEDS_MORE_EVIDENCE` state
rather than inventing a third near-identical concept.

## LLM Boundaries

`researchos.analysis.llm_call`/`validation`/`context`/`prompts` are this
package's own, independent copies (never imported from
`researchos.intelligence`/`researchos.planning`) — the established
package-independence convention every phase since Phase 6 follows.
`generate_candidate_claim`/`generate_scientific_review` use only
`researchos.llm`'s provider-agnostic abstraction, never the
Anthropic/OpenAI SDK directly.

Every LLM-assisted call is grounded in an explicit, bounded context
package (`AnalysisContext`/`ReviewContext`) built entirely from
already-persisted content the caller explicitly named — never "the
latest analysis," never the raw database. `researchos.analysis.
validation.validate_no_hallucinated_references` recursively checks every
`_id`/`_ids`-suffixed field in the model's structured response against
the exact ids the context package offered; a candidate claim citing an
id outside that set, or citing none at all, is rejected — never
persisted as an unsupported assertion. Every generation schema
explicitly excludes any approval/status field beyond what the LLM is
allowed to propose (`REVIEW_GENERATION_ALLOWED_STATUSES` excludes
`human_approved`/`rejected` at the schema level, and `reviews.py`
double-checks the actual response value defensively rather than trusting
schema enforcement strictness alone).

The LLM may summarize observations, propose candidate interpretations
and claims, identify missing evidence/threats to validity/alternative
explanations, and assess the twelve review dimensions. It may never:
approve a scientific conclusion, modify a `Metric`/`Run`/`DatasetVersion`,
approve a workflow stage, or set `ClaimApprovalStatus.APPROVED`/
`ScientificReviewStatus.HUMAN_APPROVED` — none of these are even
reachable through the LLM-facing schemas, and the service functions that
call the LLM independently re-verify the response before persisting
anything.

## Auditability

Every state change is recorded via the existing `AuditEvent` mechanism
— no parallel audit system. Event types follow the established
`<layer>.<event>` convention: `analysis.comparison_created`,
`analysis.comparison_not_comparable`, `analysis.analysis_completed`,
`analysis.claim_created`, `analysis.claim_generation_completed`,
`analysis.claim_generation_failed`, `analysis.scientific_review_created`,
`analysis.scientific_review_completed`,
`analysis.scientific_review_generation_failed`,
`analysis.scientific_review_approved`, `analysis.scientific_review_rejected`,
`analysis.scientific_review_changes_requested`, `analysis.claim_approved`,
`analysis.claim_rejected`, `analysis.claim_changes_requested`.

## Workflow Boundary

This phase does not automatically transition
`researchos.workflow`'s global stage based on any analysis result.
Analysis completion, scientific review approval, and claim approval are
three separate, independently-gated decisions — none of them, alone or
together, moves the project toward `MANUSCRIPT`/`CITATION_INTEGRITY`/
`JOURNAL_MATCHING`. `researchos.workflow.service` is neither imported
nor modified by this package.

## Domain-Neutral Design

Nothing in `researchos.analysis` contains PPE/FastViT/RetinaNet/YOLO/
PyTorch-specific logic, and no metric name (accuracy, precision, recall,
F1, mAP, IoU, ...) is ever hard-coded as a special case —
`Metric.name`/`AnalysisRecord.method` are free text, exactly as Phase
8B-2 established for `Metric.name`. `ExecutionConditions` for
comparison purposes are expressed generically through whatever a `Run`
already snapshotted (`configuration_snapshot`, `dataset_version_id`,
`dataset_fingerprint`, `environment_snapshot_id`, `seed`) — this phase
adds no CV-only or NLP-only structured comparison dimension. A future
domain adapter (computer vision, NLP, time series, tabular ML,
scientific computing) needs only to write `Metric` rows with its own
metric names and call the existing `researchos.analysis` functions —
nothing in this package needs to change.

## Dashboard & Manuscript Boundaries

This phase builds no frontend, no UI framework, no web routes, no
visual components — a future Dashboard phase consumes the backend
capabilities built here, and is out of scope for this phase. Manuscript
generation, citation formatting, journal matching, submission, and peer
review are likewise out of scope — they belong to later phases and
nothing in this package prepares data specifically for them.
