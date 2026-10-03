> Historical implementation notes. For current setup, status, and security boundaries, see [the README](../README.md) and [SECURITY.md](../SECURITY.md). Historical test counts describe earlier development checkpoints.

# Phase 7: Research Planning Layer

Date: 2026-09-17
Scope: transforms human-approved research intelligence
(`researchos.intelligence`, Phase 6) into a structured, traceable
research plan — candidate research questions, candidate scientific
contributions, methodology plans, dataset requirements, and
experimental designs — with human approval integrated through the same
`Approval`/`AuditEvent` tables Phase 4's workflow engine and Phase 6's
intelligence layer both already use. No experiment execution, no
dataset acquisition, no manuscript generation, no journal matching, no
dashboard, and no workflow-stage automation were built. No real LLM or
scholarly API call was made anywhere in this phase's implementation or
test suite.

## Core Principle

**ResearchOS does not claim that planning orchestration guarantees
scientific correctness. It guarantees structural, provenance,
project-scope, approval, and traceability constraints.**

Carried over directly from Phase 6's own core principle: an
LLM-generated planning artifact never becomes authoritative merely
because the LLM produced it. Every artifact this layer persists starts
at `PlanningApprovalStatus.CANDIDATE` — never any other value, even if
a response somehow contains one — and a downstream generation service
will only ground itself on an upstream artifact that a human has
explicitly approved.

```
LLM output -> candidate -> human approval -> eligible to ground the next stage
```

## Architecture

```
Approved ResearchGap (Phase 6, GapStatus.VALIDATED)
        │
        ▼
Research Question Generation      researchos.planning.research_questions
        │  ResearchQuestion (Phase 3, reused — planning_status=CANDIDATE)
        ▼
Contribution Generation           researchos.planning.contributions
        │  ContributionCandidate (Phase 7, NEW — distinct from NoveltyAssessment)
        ▼
        ├──────────────────────────────┐
        ▼                              ▼
NoveltyAssessment (Phase 6,      Methodology Generation
reused unmodified, now           researchos.planning.methodology
optionally linked via             │  MethodologyPlan (Phase 3, extended)
contribution_candidate_id)        ▼
                                  Dataset Requirements Generation
                                  researchos.planning.dataset_requirements
                                   │  DatasetRequirements (Phase 7, NEW)
                                   ▼
                                  Experimental Design Generation
                                  researchos.planning.experimental_design
                                   │  ExperimentalDesign (Phase 7, NEW)
                                   ▼
                                  ResearchQuestion (M:N, closes the loop —
                                  a design declares which questions it addresses)
```

```
src/researchos/planning/
├── __init__.py            # Public API — import from here
├── types.py                 # PlanningContext + outcome dataclasses
├── errors.py                  # Normalized exception hierarchy (independent of researchos.intelligence.errors)
├── prompts.py                   # Versioned prompt templates + JSON schemas (5 generation types, .v1 each)
├── context.py                     # Bounded context-package assembly from approved upstream artifacts
├── orchestration.py                 # Rules 1-4: existence / project-scope / approval-eligibility checks
├── validation.py                      # The anti-hallucination guard (planning's own copy)
├── llm_call.py                          # The one place this layer talks to an LLM (via researchos.llm)
├── research_questions.py                  # Phase 7 spec section 25
├── contributions.py                         # Phase 7 spec section 26
├── methodology.py                             # Phase 7 spec section 27
├── dataset_requirements.py                      # Phase 7 spec section 28
├── experimental_design.py                         # Phase 7 spec section 29
└── approval.py                                      # Phase 7 spec section 17
```

**What this layer never does**, enforced structurally, not just by
convention:

- Never imports `anthropic`/`openai` directly — only
  `researchos.llm.get_provider(...)`.
- Never imports or modifies `researchos.workflow.service` — workflow
  stage transitions remain that module's exclusive authority; gating
  `STAGE_07_METHODOLOGY`/`STAGE_08_DATASET`/`STAGE_09_EXPERIMENTAL_DESIGN`
  transitions on planning approvals is explicitly deferred (see
  Limitations).
- Never repurposes `NoveltyAssessment` as "the contribution" —
  `ContributionCandidate` is a distinct, new entity (see "Contribution
  Candidate vs. Novelty Assessment" below).
- Never writes to `LiteratureItem` bibliographic fields, `DatasetRecord`,
  or `Experiment`/`ExperimentResult` — those remain, respectively,
  `researchos.evidence`'s and Phase 3's own execution-tracking entities'
  exclusive authority.
- Never lets an LLM decide a `PlanningApprovalStatus.APPROVED` value —
  every generation service hard-codes `CANDIDATE` when persisting,
  and no prompt schema in this layer even offers a status field to the
  model in the first place (a stronger guarantee than Phase 6's
  schema-exclusion-plus-defensive-coercion pattern, since here there is
  nothing to defensively coerce against).
- Never imports `researchos.intelligence` — the two packages are
  independent (see "Package Independence" below); each has its own
  `errors.py`, `validation.py`-equivalent, and `llm_call.py`.

## Contribution Candidate vs. Novelty Assessment

The single most important design decision in this phase: `NoveltyAssessment`
(Phase 6) is **not** reused as "the contribution." A new entity,
`ContributionCandidate`, represents the proposed scientific contribution
itself; `NoveltyAssessment` remains exactly what Phase 6 built it to
be — an evidence-based judgment of whether a proposed contribution
appears distinct from prior work.

Reasons this distinction is load-bearing, not just conceptual:

1. **Reassessment multiplicity.** A single proposed contribution is
   realistically assessed for novelty more than once — against an
   initial literature set, then again after the literature is expanded,
   or after a reviewer requests a specific comparison. If contribution
   identity *were* the `NoveltyAssessment` row, every reassessment would
   either mutate a prior assessment's own history away, or fork the
   contribution's identity itself, breaking every downstream FK that
   pointed at the old id. `ContributionCandidate.id` stays stable across
   any number of `NoveltyAssessment` rows referencing it via the new,
   nullable `NoveltyAssessment.contribution_candidate_id`.
2. **Independent human decisions.** "We accept this as the direction
   we're pursuing" (`ContributionCandidate.planning_status`) and "this
   appears distinct from prior work" (`NoveltyAssessment.candidate_status`)
   are two decisions a human can make independently and in either order.
   `tests/planning/test_approval.py::test_contribution_and_novelty_approval_states_are_independent`
   is the regression test guarding against this ever being collapsed
   back together.
3. **No repurposed semantics.** `NoveltyAssessment.claim`/`.evidence`
   already carry one layer of Phase 6 reinterpretation from their
   original Phase 3 meaning; a second reinterpretation to also mean
   "the authoritative record of an accepted contribution" would have
   made the column's actual meaning depend on which phase's code last
   touched it.

`CONTRIBUTION_APPROVAL:<id>` (new, on `ContributionCandidate`) and
`NOVELTY_APPROVAL:<id>` (Phase 6's own, unchanged, on `NoveltyAssessment`)
are therefore two separate approval gates, not one.

## Database Changes

One migration
(`migrations/versions/18d5e18a097f_research_planning_layer.py`), built
by autogenerating against the actual Phase 6 schema and hand-fixing what
autogenerate cannot detect (see below).

**New tables:**

| Table | Purpose |
|---|---|
| `contribution_candidates` | One proposed scientific contribution — title, description, contribution_type, `planning_status`, `version`, generation provenance |
| `contribution_candidate_questions` | The M:N association: which `ResearchQuestion`(s) a contribution addresses |
| `dataset_requirements` | What the research needs from its data — deliberately distinct from `DatasetRecord` (an actual registered/acquired dataset) |
| `experimental_designs` | A planning-only design — baselines, ablations, metrics, comparison strategy — deliberately distinct from `Experiment` (Phase 3's execution-tracking record) |
| `experimental_design_questions` | The M:N association: which `ResearchQuestion`(s) a design addresses |

**Extended existing tables:**

- **`research_questions`** (Phase 3, otherwise untouched): `hypothesis`
  (nullable — not every research question implies a testable
  hypothesis) and `planning_status` (new shared
  `PlanningApprovalStatus` enum). `QuestionStatus`
  (OPEN/ANSWERED/DROPPED) is left completely alone — it tracks the
  question's own research lifecycle, an independent axis from whether a
  human has approved it for planning purposes. Traceability to the
  approved gap that motivated a generated question uses the *existing*
  `research_gaps.research_question_id` FK (Gap → Question) — no second,
  duplicate relationship was added.
- **`methodology_plans`** (Phase 3, otherwise untouched):
  `planning_status`, `methodology_type`, `components`, `assumptions`,
  `risks`, `reproducibility_requirements` (structured JSON per Phase 7
  spec section 6), generation provenance, and
  `contribution_candidate_id`/`contribution_candidate_version`/
  `contribution_candidate_status_at_generation` (the upstream
  dependency + its generation-time snapshot). `MethodologyStatus`
  (DRAFT/ACTIVE/SUPERSEDED) is left completely alone — it tracks which
  version is currently in effect, an independent axis from whether a
  human has approved that version's content.
  `create_methodology_version()`'s existing auto-incrementing
  `(project_id, version)` versioning is reused unmodified.
- **`novelty_assessments`** (Phase 6, otherwise untouched):
  `contribution_candidate_id`, nullable, backward compatible with every
  existing `NoveltyAssessment` row (which has none).

All five new/extended enum columns
(`ResearchQuestion.planning_status`, `ContributionCandidate.planning_status`,
`MethodologyPlan.planning_status`, `DatasetRequirements.planning_status`,
`ExperimentalDesign.planning_status`) share **one** enum,
`PlanningApprovalStatus`, rather than five near-identical
entity-specific enums — unlike Phase 6's `GapStatus`/
`NoveltyCandidateStatus`, none of these five columns predates this
phase, so there was no pre-existing value set to reconcile with, and a
single shared enum is strictly simpler. All five use
`create_constraint=True` (a real `CHECK` constraint), continuing the
Phase 4/5/6 practice.

**A gotcha autogenerate could not catch:** `evidence_links.subject_type`'s
existing `CHECK` constraint needed to be widened by hand to admit the
five new `EvidenceSubjectType` members this phase adds
(`RESEARCH_QUESTION`, `CONTRIBUTION_CANDIDATE`, `METHODOLOGY_PLAN`,
`DATASET_REQUIREMENTS`, `EXPERIMENTAL_DESIGN`) — Alembic's autogenerate
diffs added/removed columns and tables, not a `CHECK` constraint's
*value set* on an already-existing enum column. Verified directly
against the rendered `CREATE TABLE` SQL during migration testing, not
assumed. The same SQLite-batch-mode "drop the `CHECK` constraint before
dropping the column it constrains" ordering this codebase has now hit
three times (Phase 4, Phase 6, and again here for both
`research_questions.planning_status` and
`methodology_plans.planning_status`) was needed again in `downgrade()`.

## Repository Layer

New functions in `researchos.db.repository`, following the existing
explicit-session, no-hidden-commit convention exactly:
`update_research_question`, `create_contribution_candidate`,
`get_contribution_candidate`, `list_contribution_candidates`,
`update_contribution_candidate`, `link_contribution_candidate_question`,
`list_contribution_candidate_questions`, `update_methodology_plan`,
`create_dataset_requirements`, `get_dataset_requirements`,
`list_dataset_requirements`, `update_dataset_requirements`,
`create_experimental_design`, `get_experimental_design`,
`list_experimental_designs`, `update_experimental_design`,
`link_experimental_design_question`,
`list_experimental_design_questions`. `create_research_question` and
`create_methodology_version` gained the new optional fields listed
above (fully backward compatible — every new parameter defaults to
`None`/`CANDIDATE`/`1`). `record_novelty_assessment` gained an optional
`contribution_candidate_id` parameter, and
`researchos.intelligence.analyze_novelty_candidate()` gained the same
parameter, passed straight through — the one place this phase touches
Phase 6 production code beyond the approval-dispatch extraction below.
The two association-table link functions validate that both endpoints
exist *and* belong to the same project before inserting — never
silently mixed across projects.

## Shared Approval Dispatch

`researchos.db.approval_dispatch` (new): the generic "which entity,
which stage-key prefix, which status to set on approve/reject/
request-changes" dispatch mechanics, extracted from what was originally
a private copy inside `researchos.intelligence.approval`. Contains no
domain knowledge of any specific entity type — callers supply an
`EntitySpec` (get/update_status functions, approved/rejected/
changes-requested values, and their own three exception classes), so
each layer's public error surface is completely unaffected by the
extraction: `researchos.intelligence.approval` was refactored to call
this shared module and still raises `researchos.intelligence.errors.*`
exactly as before (verified: all 67 pre-existing intelligence tests
pass unmodified), while `researchos.planning.approval` raises its own,
independent `researchos.planning.errors.*` exceptions. Phase 4 remains
the sole authority over the underlying `Approval`/`AuditEvent`/
`ApprovalDecision` tables and `is_human_actor` — this module only
removes duplication of the bookkeeping around them.

## Package Independence

`researchos.planning` does not import `researchos.intelligence`, and
vice versa (aside from the one explicit, optional integration point:
`analyze_novelty_candidate(..., contribution_candidate_id=...)`
described above). Each package has its own `errors.py`, its own small
anti-hallucination `validation.py` (an intentional, small duplication of
a *generic algorithm* — walk any `_id`/`_ids`-suffixed key — not of any
domain-specific data or behavior), and its own `llm_call.py`. This
mirrors how `researchos.intelligence` itself never imported
`researchos.evidence`'s internals, only its `LiteratureItem` model —
each phase's package is a sibling, not a layer stacked inside another
phase's namespace.

## Planning Context Assembly

`researchos.planning.context` builds a bounded `PlanningContext` for
each generation type from explicitly-supplied, already-approved
upstream artifact ids — never the raw ORM row, never arbitrary internal
fields, and never a bare id with no content (Phase 7 spec section 24:
"the context package must contain actual approved content, not merely
IDs"). Deliberately not a reuse of
`researchos.intelligence.evidence_package` — that module is hard-typed
to project `LiteratureItem` rows into a prompt; this layer's context is
assembled from multiple upstream table types
(`ResearchGap`/`ResearchQuestion`/`ContributionCandidate`/
`MethodologyPlan`/`DatasetRequirements`), which does not fit that
module's shape.

Every context builder enforces `researchos.planning.orchestration`'s
four structural rules **before** assembling anything or calling an LLM:

1. **Explicit upstream ids.** Every generation function takes required,
   explicit ids — never `get_latest_contribution()`/
   `get_pending_methodology()`. Verified directly:
   `tests/planning/test_methodology_generation.py::test_unapproved_contribution_is_refused_before_any_llm_call`
   asserts the fake provider's `calls` list stays empty when the check
   fails.
2. **Existence.** An unknown id raises `UnknownPlanningEntityError`
   immediately.
3. **Project isolation.** An id that exists but belongs to a different
   project raises `CrossProjectReferenceError` — never silently mixed.
4. **Approval eligibility.** Only an upstream artifact whose approval
   status is the approved value (`PlanningApprovalStatus.APPROVED` for
   this phase's own entities; `GapStatus.VALIDATED` for the one Phase 6
   entity this layer reads from) may ground a downstream generation —
   `CANDIDATE`/`CHANGES_REQUESTED`/`REJECTED` raises
   `UpstreamNotApprovedError`.

Grounded generation: each context's `prompt_json` embeds the actual
approved upstream content (a methodology's real description/components,
not just its id), so a downstream generator's proposal is seeded by
what was actually approved rather than independently reinventing it —
directly addressing the "do not implement four independent LLM
generators that can produce mutually inconsistent plans" requirement.
No upstream artifact is ever mutated by a downstream generation call —
each service writes only to its own table, its own association rows,
and its own evidence links.

## Anti-Hallucination Safeguards

`researchos.planning.validation` (self-contained, not imported from
`researchos.intelligence.response_validation`, though algorithmically
identical): `extract_referenced_ids()`/`validate_no_hallucinated_references()`
recursively find every integer under any `_id`/`_ids`-suffixed key and
compare against the ids a `PlanningContext` explicitly allowed.
Any claim/contribution/design entry citing an id outside its context is
rejected — the whole entry is dropped for a list-producing service
(research questions, contributions), or the whole response is rejected
for a single-artifact service (methodology, dataset requirements,
experimental design), never partially trusted.

## Versioning / Immutable History

Regeneration always creates a **new row**, never overwrites an existing
one. Two distinct versioning shapes exist, chosen per entity's actual
concurrency model rather than one scheme forced onto all of them:

- **`MethodologyPlan`**: `create_methodology_version()`'s existing
  per-project auto-incrementing `version` (Phase 3) is exercised
  unmodified by `generate_methodology_plan()` — a v1 plan sent back for
  changes stays exactly as it was, and a fresh call produces v2,
  verified directly by
  `tests/planning/test_methodology_generation.py::test_regeneration_creates_a_new_version_never_overwrites`.
  This is a project-wide counter because a project only ever has one
  "current" evolving methodology.
- **`ContributionCandidate` and `ExperimentalDesign`** (fixed during the
  Phase 7 post-implementation audit remediation — see below): each has
  a nullable, self-referential `supersedes_id` FK, `UniqueConstraint`-
  protected so a given row can be superseded by at most one later
  version — a real, traceable, unbranching lineage. Unlike
  `MethodologyPlan`, these are **not** a project-wide counter, because
  multiple independent contributions/designs can legitimately coexist
  in one project at once (e.g. two unrelated proposed contributions
  both legitimately at "version 1" simultaneously); a caller passes
  `supersedes_id=<prior_id>` explicitly to `generate_contribution_candidates()`/
  `generate_experimental_design()` to mark a call as a targeted
  regeneration of one specific prior row (`version` then becomes
  `prior.version + 1` automatically); omitting it always starts a new,
  independent lineage at `version=1`. Verified by
  `tests/planning/test_contribution_generation.py::test_regenerating_via_supersedes_id_creates_a_real_v2_and_preserves_v1`
  (and the equivalent in `test_experimental_design_generation.py`), plus
  `test_independent_contributions_do_not_share_a_lineage` and
  `test_superseding_the_same_design_twice_is_rejected` (the
  `UniqueConstraint` refusing a branching lineage).

## Generation-Time Upstream Snapshot

Every downstream artifact records, for each upstream artifact it
consumed: the upstream id (via its FK column), the upstream's version
(when it has one), and the upstream's approval status *at the moment of
generation* — never only the status, so a reviewer can always
reconstruct exactly which approved version grounded a given plan (Phase
7 spec section 15). For single-valued FK relationships
(`MethodologyPlan.contribution_candidate_*`,
`DatasetRequirements.methodology_plan_*`,
`ExperimentalDesign.methodology_plan_*`/`.dataset_requirements_*`) this
is stored as sibling columns on the downstream row for O(1) lookup. For
multi-valued relationships (which research questions a contribution or
design addresses), the snapshot is recorded in the generation's
`AuditEvent.metadata_["upstream_snapshots"]` instead, since a single
scalar column doesn't fit a multi-valued relationship — the association
table itself (`contribution_candidate_questions`/
`experimental_design_questions`) carries only the current structural
link, not a point-in-time snapshot.

## No Cascading Invalidation

An explicit architectural rule (Phase 7 spec section 16), verified by
`tests/planning/test_approval.py::test_rejecting_approved_upstream_does_not_touch_already_generated_downstream`:
rejecting an upstream artifact after a downstream plan was already
generated from its approved version does **not** automatically delete,
reject, or modify the downstream artifact. The downstream row keeps
existing, keeps its own `planning_status` untouched, and keeps its
original generation-time snapshot exactly as it was — it is not
retroactively rewritten to reflect the upstream's new status. A future
reviewer or reconciliation process can compare a downstream artifact's
stored snapshot against the upstream's *current* status to spot the
inconsistency; this phase does not build that reconciliation process
itself (see Limitations).

## Human Approval Integration

`researchos.planning.approval` provides six approval-decision function
triples (approve/reject/request_changes), five of them new:

```python
from researchos import planning

planning.approval.approve_research_question(question_id, actor="user:pi", comment="well-posed")
planning.approval.approve_contribution(contribution_id, actor="user:pi")
planning.approval.approve_methodology_plan(plan_id, actor="user:pi")
planning.approval.approve_dataset_requirements(requirements_id, actor="user:pi")
planning.approval.approve_experimental_design(design_id, actor="user:pi")
```

`NOVELTY_APPROVAL:<id>` (the sixth gate) is **not** redefined here — it
remains exclusively `researchos.intelligence.approval`'s, unchanged,
since a `NoveltyAssessment` decision and a `ContributionCandidate`
decision are independent (see above).

- **The LLM cannot approve its own output**: every decision function
  requires `is_human_actor(actor)` (via the shared dispatcher); an
  agent actor raises `HumanOnlyActionError` immediately, before any row
  is touched — verified for all six gate types (five planning + the
  reused novelty gate) in
  `tests/planning/test_approval.py::test_agent_actor_cannot_approve_any_planning_gate`.
- **Every decision is atomic**: the `Approval` row's decision, the
  candidate's own `planning_status`, and an `AuditEvent` all commit in
  one `session_scope()` — the same pattern Phase 4/6 use.
- **A `CHANGES_REQUESTED` decision is not terminal**; `APPROVED`/
  `REJECTED` are — a second decision attempt raises
  `ApprovalAlreadyDecidedError`.

## Prompt Versioning

Every generation type has a stable, persisted `(prompt_name,
prompt_version)` pair: `research_question_generation.v1`,
`contribution_generation.v1`, `methodology_generation.v1`,
`dataset_requirements_generation.v1`,
`experimental_design_generation.v1` (`researchos.planning.prompts`).
No schema offers a `planning_status`/approval field to the model at
all — every generation service hard-codes `CANDIDATE` regardless of
what a response contains, verified by
`tests/planning/test_llm_provider_integration.py::test_llm_never_persists_an_approved_status_even_if_it_tries`.

## Evidence Traceability

Reuses `EvidenceLink` (Phase 6) directly — no second evidence-linking
mechanism. `EvidenceSubjectType` gained five new members
(`RESEARCH_QUESTION`, `CONTRIBUTION_CANDIDATE`, `METHODOLOGY_PLAN`,
`DATASET_REQUIREMENTS`, `EXPERIMENTAL_DESIGN`); `create_evidence_link()`
validates `subject_id` against the correct table for each, exactly as
it already did for the four Phase 6 subject types — a cross-table id
collision is rejected, not silently accepted (verified for all five new
subject types in `tests/planning/test_evidence_link.py`). No planning
entity gained a DOI/author/title column; `LiteratureItem` remains
exclusively `researchos.evidence`'s.

## Testing

`tests/planning/` (109 tests, `pytest tests/planning -q`). Every test
injects a `FakeLLMProvider` (`tests/planning/fakes.py`) via each
service's `provider=` parameter — no test in this suite makes, or could
make, a real LLM or scholarly API call. Fixtures follow the exact
pattern established in `tests/db`/`tests/workflow`/`tests/evidence`/
`tests/intelligence`: a fresh temporary SQLite database per test,
migrated via the real Alembic path.

| File | Covers |
|---|---|
| `test_context_and_upstream_validation.py` | Rules 1-4 for every context builder: unknown id, cross-project id, not-yet-approved upstream, valid case |
| `test_research_question_generation.py` | Candidate never pre-approved, hallucinated literature id rejected, blank text rejected, LLM failure audited, max_questions respected |
| `test_contribution_generation.py` | Candidate never pre-approved, no-supporting-question rejection, hallucinated question id rejected, never touches NoveltyAssessment; **regeneration via `supersedes_id` produces a real v2 (v1 unchanged), independent contributions don't share a lineage, cross-project `supersedes_id` rejected** |
| `test_methodology_generation.py` | Candidate with upstream snapshot, unapproved contribution refused before any LLM call, blank description rejected, regeneration creates a new version (v1 unchanged, v2 new) |
| `test_dataset_requirements_generation.py` | Candidate with upstream snapshot, never references a real DatasetRecord, unapproved methodology refused |
| `test_experimental_design_generation.py` | Candidate + question links, addressed-question-outside-given-set rejected, never creates an Experiment; **regeneration via `supersedes_id` produces a real v2, independent designs don't share a lineage, superseding the same design twice is rejected (unbranching lineage)** |
| `test_approval.py` | Candidates never pre-approved; agent blocked on all six gate types (five new + reused novelty); atomic audit content; rejection terminal; changes-requested reopens a round; not-found handling; **contribution/novelty independence**; **no cascading invalidation**; **`previous_status` correctness for all five planning gates (parametrized)** |
| `test_evidence_link.py` | All five new EvidenceSubjectType members accepted for a real subject; cross-table id collision rejected; cross-project subject rejected |
| `test_association_tables.py` | Both association tables reject a duplicate pair, a cross-project pair, and a missing endpoint |
| `test_migration.py` | Upgrade creates all new tables/columns; downgrade-then-upgrade round-trips cleanly; CHECK constraints enforced (including the widened `evidencesubjecttype`); FKs and uniqueness constraints declared; **upgrade against a database with pre-existing Phase 6 rows succeeds and backfills correctly (audit remediation); the inherited Phase 6 gap fixed in isolation; downgrade preserves pre-existing rows throughout** |
| `test_reproducibility.py` | provider/model/prompt_name/prompt_version and the generation-time upstream snapshot persisted for every generation type |
| `test_llm_provider_integration.py` | Provider abstraction used (no registry touch when injected), malformed response rejected, no secrets in prompts or audit events, LLM cannot self-assign APPROVED |

Run with:
```powershell
<repository-root>\.venv\Scripts\python.exe -m pytest tests\planning -v
```

Full-suite regression after this phase's audit remediation:
**496/496 passing** (`tests/planning` 109, `tests/intelligence` 69 —
both up from their pre-remediation counts of 95 and 67 respectively,
purely from the regression tests the remediation added; every
pre-existing test's *behavior* is unchanged).

## Audit Remediation

A post-implementation, read-only audit (performed after this phase's
initial implementation, before any commit) reproduced four findings
independently against live databases and code, none of them assumed
from memory. All four were remediated in place, each with regression
tests added:

- **Migration safety (was HIGH)** — `research_questions.planning_status`,
  `methodology_plans.planning_status` (this migration), and
  `novelty_assessments.candidate_status` (the pre-existing Phase 6
  migration) were `NOT NULL` columns added to already-existing tables
  with no `server_default`, which the test suite never caught because
  every test builds a database from empty via the full chain in one
  run. Reproduced directly: upgrading a database with pre-existing rows
  in those tables failed with `IntegrityError`. Fixed with a temporary
  `server_default` (backfills old rows during the SQLite batch-mode
  table rebuild, then is dropped again immediately so the final schema
  is byte-identical to before) in both migration files — see each
  file's own docstring for why editing the already-committed Phase 6
  migration in place was judged safe here (unreleased project; no
  database anywhere has actually run it). Covered by
  `tests/planning/test_migration.py::test_phase7_upgrade_succeeds_against_database_with_preexisting_phase6_rows`,
  `test_phase7_upgrade_then_downgrade_preserves_preexisting_rows`, and
  `test_phase6_upgrade_succeeds_against_database_with_preexisting_novelty_assessment_row`.
- **Versioning (was MEDIUM)** — `ContributionCandidate.version` and
  `ExperimentalDesign.version` existed but were never incremented. Fixed
  with a `supersedes_id` self-FK on each (see Versioning section
  above) rather than the project-wide counter `MethodologyPlan` uses,
  since multiple independent lineages can coexist per project.
- **`NoveltyAssessment` approval audit metadata (was LOW)** —
  `researchos.db.approval_dispatch`'s status lookup guessed the status
  attribute from a fixed priority list, which picked Phase 3's dormant
  `status` field over Phase 6's actually-changing `candidate_status` for
  this one entity, reproduced directly against a live database
  (`previous_status` read `"pending"` instead of `"not_assessed"`).
  Fixed by making `EntitySpec.status_attr` an explicit, required field
  each caller declares (`"approval_status"`/`"status"`/
  `"candidate_status"`/`"planning_status"` as appropriate) instead of a
  guessed priority order. Covered by
  `tests/intelligence/test_approval.py::test_novelty_approval_audit_event_records_correct_previous_status`
  and a parametrized regression across all five Phase 7 gates in
  `tests/planning/test_approval.py::test_planning_gate_audit_event_records_correct_previous_status`.
- **Repository-layer error typing (was LOW)** — some repository
  functions raise the generic `NotFoundError` for both "missing" and
  "wrong project," rather than the distinctly-typed errors
  `researchos.planning.orchestration` raises. Judged a deliberate
  layering choice (matching Phase 6's own `create_evidence_link()`
  precedent) rather than a defect worth a new error hierarchy —
  documented explicitly in `researchos.db.errors.NotFoundError`'s and
  `researchos.db.repository`'s own docstrings instead of changed.

## Limitations

- **No reconciliation/staleness surfacing process** — a downstream
  artifact whose upstream was later rejected keeps its stale
  generation-time snapshot (by design, see "No Cascading Invalidation"),
  but nothing in this phase actively surfaces "this plan rests on a
  since-rejected artifact" to a reviewer; that comparison is currently
  only possible by a caller explicitly checking the snapshot against
  the upstream's live status.
- **No workflow-stage gating** — `STAGE_07_METHODOLOGY`/
  `STAGE_08_DATASET`/`STAGE_09_EXPERIMENTAL_DESIGN` transitions are not
  gated on any planning approval existing; `researchos.workflow.service`
  is untouched, matching the same deferral Phase 6 already documented
  for its own stages.
- **No literature-evidence citation for methodology/dataset-requirements/
  experimental-design content** — only research-question and
  contribution generation support citing specific `LiteratureItem`
  evidence; the later three stages validate only the structural
  upstream ids they were explicitly given (contribution/methodology/
  dataset-requirements/research-question ids), not open-ended
  literature citations, keeping the anti-hallucination surface matched
  to where evidence-grounding is actually central to each stage.
- **Field mappings/prompt effectiveness not verified against a real
  LLM** — per this phase's explicit no-real-API-calls instruction, the
  five prompts have not been validated against Anthropic's or OpenAI's
  actual structured-output behavior; recommend the same kind of
  smoke-test Phase 5.1 performed for the evidence adapters, and Phase
  6's own doc recommended for itself, before relying on this layer's
  output quality in production.

## Future Work

- A `supersedes_id`/lineage-grouping mechanism for `ContributionCandidate`
  and `ExperimentalDesign`, mirroring `MethodologyPlan`'s existing
  per-project auto-incrementing version more precisely once a concrete
  need for it is identified.
- A reconciliation view/service surfacing downstream artifacts whose
  recorded upstream snapshot no longer matches that upstream artifact's
  live status (`approval.get_pending_planning_approvals()` already
  returns the review queue; a "stale grounding" queue is a natural
  companion, not built here).
- Extending the workflow engine (Phase 4) to gate
  `STAGE_07`/`STAGE_08`/`STAGE_09` transitions on at least one approved
  planning artifact of the corresponding kind — deliberately not done
  in this phase, which was instructed not to modify the workflow engine.
- A real-LLM smoke test (mirroring Phase 5.1 and Phase 6's own deferred
  item) once the user is ready to supply credentials and approve real
  API calls.
- Literature-evidence citation support for methodology/dataset-
  requirements/experimental-design generation, if a concrete need for
  grounding those stages directly in specific papers (rather than in
  their approved upstream planning artifacts) emerges.
