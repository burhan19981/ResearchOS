> Historical implementation notes. For current setup, status, and security boundaries, see [the README](../README.md) and [SECURITY.md](../SECURITY.md). Historical test counts describe earlier development checkpoints.

# Phase 4: Research Workflow Engine

Date: 2026-09-17
Scope: A deterministic, auditable, human-controlled state machine
governing `ResearchProject` stage transitions and approval gates,
built entirely on top of the Phase 3 persistence layer. No agents, no
literature search, no novelty/dataset analysis, no experiment
execution, no manuscript generation, no dashboard, and no LLM/external
API calls were implemented or made in this phase.

## Core Principle

**The LLM does not control workflow state directly.** Everything in
`researchos.workflow` is pure, deterministic Python and SQL — no
module in this package imports `researchos.llm` or calls any external
service. Agents may, in a future phase, call `request_transition()` to
*propose* a change, but only the policy in `researchos.workflow.policy`
decides whether that proposal executes immediately, waits for a human,
or is refused outright, and only `approve()` (always a human act) ever
authorizes a gated change.

## Architecture

```
src/researchos/workflow/
├── __init__.py     # Public API — import from here
├── stages.py         # The 20 canonical WorkflowStage values + linear ordering
├── policy.py          # Policy enum + deterministic get_policy() + actor convention
├── errors.py           # Domain errors (10 types, see below)
└── service.py            # get_current_stage / transition / approve / pause / ... 

migrations/versions/
└── e633d3930fa8_add_project_status_rejected.py   # Phase 4's one schema change
```

`researchos.workflow` depends only on `researchos.db` (models,
repository, engine) — nothing in `researchos.db` was told about
workflow concepts; the workflow layer built entirely on Phase 3's
existing, unmodified API surface except for one addition (below).

## The One Schema Change, and Why

Phase 3 deliberately left `ResearchProject.current_stage` as a free
`String(200)` column, its own docstring noting "a future
workflow-engine phase may formalize these." Phase 4 **is** that phase —
but it formalizes `current_stage` entirely at the Python layer
(`researchos.workflow.stages.WorkflowStage`), not by changing the
column's type. Reasons:

- The column already accepts any string; no migration is needed to
  *use* it as a 20-value enum from Python.
- `current_stage` is NULL for every project until its first workflow
  transition (Phase 3's `create_project()` never set it). Rather than
  changing that, `get_current_stage()` treats a NULL value as the
  implicit `STAGE_01_IDEA` — the *only* implicit state; every
  subsequent change is an explicit, audited `transition()`.
- An unrecognized value (corruption, or a future migration mistake)
  raises `InvalidWorkflowStateError` rather than being silently
  coerced — see `tests/workflow/test_invalid_transitions.py::test_corrupted_current_stage_value_raises_on_read`.

The one schema change Phase 4 *does* make: **`ProjectStatus` gained a
`REJECTED` member** (alongside the existing `ACTIVE`/`PAUSED`/
`COMPLETED`/`ARCHIVED`), for `reject_project()`. `PAUSED`/`ARCHIVED`/
`COMPLETED` already existed and needed no schema change; only
`REJECTED` was new, so only one small, targeted migration was needed
(`migrations/versions/e633d3930fa8_add_project_status_rejected.py`).

### A discovered gap, and how this migration also fixes it

While writing that migration, direct inspection of the live SQLite
schema showed that **`ResearchProject.status`'s enum column had no
database-level `CHECK` constraint at all** — despite
`docs/PHASE3_DATABASE.md` documenting `native_enum=False` as producing
one. In SQLAlchemy 2.0, `Enum(..., native_enum=False)` alone renders as
a plain `VARCHAR`; the `CHECK` constraint requires `create_constraint=True`
as well, which Phase 3 did not set on any of its 14 enum columns. A raw
SQL write (bypassing the ORM) could previously insert any string into
`status`, since only `validate_strings=True`'s Python-side check
existed, not real DB enforcement — verified directly:

```
CREATE TABLE "research_projects" (
    ...
    status VARCHAR(32) NOT NULL,   -- no CHECK, before this migration
    ...
)
```

**Fix scope in this phase:** `models._enum_column()` gained an
opt-in `create_constraint: bool = False` parameter — defaulting to
`False` so the other 13 enum columns' migration history stays exactly
in sync with their model definitions (flipping the shared default
would make every one of them look like a pending, undocumented
autogenerate diff). Only `ResearchProject.status` passes
`create_constraint=True`, and the Phase 4 migration was written to
match, since it already needed to touch this exact column and
constraint for `REJECTED`. Verified directly (see the migration's
docstring and `tests/db` — the constraint now genuinely rejects
invalid values via raw SQL, not just through the ORM).

**Left for a future decision, not fixed here:** the other 13 enum
columns across Phase 3's tables (`IdeaStatus`, `QuestionStatus`,
`EvidenceStatus`, `GapStatus`, `NoveltyStatus`, `MethodologyStatus`,
`ExperimentStatus`, `ManuscriptStatus`, `JournalCandidateStatus`,
`ApprovalDecision`) still lack a real `CHECK` constraint, protected
only by ORM-side validation. Retrofitting all of them is a
multi-table Phase-3-schema migration outside a "workflow engine" phase's
declared scope, so it was not done without explicit direction — flagged
here for you to decide whether/when to schedule it.

## The 20 Canonical Stages

Defined in `researchos.workflow.stages.WorkflowStage`, in this fixed
linear order (`STAGE_ORDER`):

```
STAGE_01_IDEA
STAGE_02_INITIAL_VALIDATION
STAGE_03_LITERATURE_SEARCH
STAGE_04_LITERATURE_MAPPING
STAGE_05_RESEARCH_GAP
STAGE_06_NOVELTY_VERIFICATION
STAGE_07_METHODOLOGY
STAGE_08_DATASET
STAGE_09_EXPERIMENTAL_DESIGN
STAGE_10_IMPLEMENTATION
STAGE_11_EXPERIMENTS
STAGE_12_RESULTS_ANALYSIS
STAGE_13_SCIENTIFIC_REVIEW
STAGE_14_MANUSCRIPT
STAGE_15_CITATION_INTEGRITY
STAGE_16_JOURNAL_SELECTION
STAGE_17_SUBMISSION_PREPARATION
STAGE_18_PEER_REVIEW
STAGE_19_REVISION
STAGE_20_FINAL
```

### Administrative states (not in the stage graph)

`PAUSED`, `REJECTED`, `ARCHIVED`, `COMPLETED` are **not** `WorkflowStage`
values — they live on the pre-existing `ResearchProject.status`
(`ProjectStatus`) field, orthogonal to `current_stage`. A paused
project retains its `current_stage` exactly where it was (e.g. paused
mid-`STAGE_07_METHODOLOGY` still reads `current_stage=STAGE_07_METHODOLOGY`,
`status=PAUSED`) — pausing never overwrites pipeline position. This
was a deliberate design choice over overloading `current_stage` with a
mixed vocabulary: it keeps "where in the pipeline" and "is work
currently allowed to proceed" as two independently-answerable
questions. `COMPLETED` is not automated by anything in Phase 4 — no
service function sets it (a future phase may decide `COMPLETED` should
follow from reaching `STAGE_20_FINAL`, but that decision belongs there).

## Transition Graph

- **Forward:** exactly one canonical step at a time
  (`STAGE_NN → STAGE_(NN+1)`). Skipping stages is always rejected
  (`InvalidTransitionError`) — "do not silently skip canonical
  research stages" is enforced structurally, not by convention.
- **Backward:** a move to *any* earlier stage is structurally legal
  (not just the immediately preceding one — a fundamental flaw found
  in `STAGE_18_PEER_REVIEW` might legitimately require returning all
  the way to `STAGE_07_METHODOLOGY`), but **always** requires approval
  regardless of which stages are involved, and is tagged
  `transition_type: "backward"` in its audit event. This is a
  deliberate simplification over hand-curating which specific backward
  pairs are "scientifically valid" — that would be an opinion this
  project has no special authority to encode; instead, forward jumps
  of any size are flatly forbidden (no skipping), and any backward
  move is allowed but always gated on an explicit, recorded reason.
- **Same-stage "transition":** rejected as a no-op
  (`InvalidTransitionError`).

## Approval Policy

Three deterministic tiers (`researchos.workflow.policy.Policy`):

| Policy | Meaning |
|---|---|
| `AUTO_ALLOWED` | Any actor (agent or human) — applies immediately, no approval record |
| `APPROVAL_REQUIRED` | Any actor may *request* it; only a human may `approve()`/`reject()`/`request_changes()` it |
| `HUMAN_ONLY` | Only a human actor may even *request* it (an agent gets `HumanOnlyActionError` immediately); still requires human approval after that |

### Forward-edge policy table, mapped to the spec's 11 named gates

| Destination stage | Policy | Spec gate # |
|---|---|---|
| STAGE_02_INITIAL_VALIDATION | APPROVAL_REQUIRED | 1. Accepting the idea as the active direction |
| STAGE_03_LITERATURE_SEARCH | AUTO_ALLOWED | — |
| STAGE_04_LITERATURE_MAPPING | AUTO_ALLOWED | — |
| STAGE_05_RESEARCH_GAP | AUTO_ALLOWED | — |
| STAGE_06_NOVELTY_VERIFICATION | APPROVAL_REQUIRED | 2. Accepting a proposed research gap |
| STAGE_07_METHODOLOGY | APPROVAL_REQUIRED | 3. Accepting a novelty claim |
| STAGE_08_DATASET | APPROVAL_REQUIRED | 4. Approving the methodology |
| STAGE_09_EXPERIMENTAL_DESIGN | APPROVAL_REQUIRED | 5. Approving dataset/split decisions |
| STAGE_10_IMPLEMENTATION | AUTO_ALLOWED | — |
| STAGE_11_EXPERIMENTS | APPROVAL_REQUIRED | 6. Launching expensive experiments |
| STAGE_12_RESULTS_ANALYSIS | AUTO_ALLOWED | — |
| STAGE_13_SCIENTIFIC_REVIEW | AUTO_ALLOWED | — |
| STAGE_14_MANUSCRIPT | AUTO_ALLOWED | — |
| STAGE_15_CITATION_INTEGRITY | APPROVAL_REQUIRED | 7. Approving major manuscript changes |
| STAGE_16_JOURNAL_SELECTION | AUTO_ALLOWED | — |
| STAGE_17_SUBMISSION_PREPARATION | APPROVAL_REQUIRED | 8. Selecting the target journal |
| STAGE_18_PEER_REVIEW | APPROVAL_REQUIRED | 9. Preparing final submission |
| STAGE_19_REVISION | AUTO_ALLOWED | — |
| STAGE_20_FINAL | **HUMAN_ONLY** | 10. Final response to reviewers + 11. Moving to final/publication status |

Gates 10 and 11 are the same real-world moment in this stage-level
model (Phase 4 has no separate "action" layer beneath a stage — that
belongs to a future agent/task phase), so both map to the single
`HUMAN_ONLY` gate on reaching `STAGE_20_FINAL`.

**Backward moves:** always `APPROVAL_REQUIRED`, regardless of stage.

**Administrative actions:** `pause_project`/`resume_project` are
`AUTO_ALLOWED` (reversible, low-risk); `archive_project`/`reject_project`
are `APPROVAL_REQUIRED` (consequential enough to need sign-off, but not
elevated to `HUMAN_ONLY` — that tier is reserved for the one
genuinely-named case in the spec, publication).

## HUMAN_ONLY Rules and the Actor Convention

ResearchOS has no real identity/authentication system yet. Until one
exists, `researchos.workflow.policy.is_human_actor()` uses an explicit,
documented placeholder: an actor string prefixed with `"agent:"`
(case-insensitive) is agent-originated; everything else (`"system"`,
`"user:alice"`, `"human:bob"`) is human. This is deliberately visible
rather than hidden, since it's the one fact a future real-auth
integration most needs to replace correctly.

Two independent enforcement points:

1. **Requesting.** `request_transition()` raises `HumanOnlyActionError`
   immediately if an agent actor attempts a `HUMAN_ONLY` edge — it
   never even creates a pending `Approval`.
2. **Deciding.** `approve()` / `reject()` / `request_changes()` *always*
   require a human actor, for every gated action regardless of tier —
   an agent approving its own `APPROVAL_REQUIRED` request would defeat
   the point of requiring approval at all.

`transition()` (as opposed to `request_transition()`) never applies a
gated edge under any circumstances, for any actor — it always raises
`ApprovalRequiredError`/`HumanOnlyActionError` for `APPROVAL_REQUIRED`/
`HUMAN_ONLY` edges. The **only** way a gated change is ever applied is
through `approve()`. This is what makes the workflow engine — not any
caller — the sole authority over whether a gated change has actually
been authorized.

## Workflow Service

Two tiers, matching `researchos.db.repository`'s own layering:

**Primitives** (explicit `Session`, no commit — composable within a
caller's own transaction):
```python
get_current_stage(session, project_id) -> WorkflowStage
get_allowed_transitions(session, project_id) -> list[AllowedTransition]
can_transition(session, project_id, target_stage) -> bool
request_approval(session, project_id, stage_key, actor, reason=None) -> Approval
get_pending_approvals(session, project_id=None) -> list[Approval]
```

**Orchestrated operations** (own their transaction via `session_factory`
— each call is one atomic unit):
```python
request_transition(project_id, target_stage, actor, reason=None, *, expected_current_stage=None) -> TransitionOutcome
transition(project_id, target_stage, actor, reason=None, *, expected_current_stage=None) -> ResearchProject
pause_project(project_id, actor, reason=None) -> ResearchProject
resume_project(project_id, actor, reason=None) -> ResearchProject
archive_project(project_id, actor, reason=None) -> TransitionOutcome
reject_project(project_id, actor, reason=None) -> TransitionOutcome
approve(approval_id, actor, comment=None) -> Approval
reject(approval_id, actor, comment=None) -> Approval
request_changes(approval_id, actor, comment=None) -> Approval
```

`request_transition()` vs `transition()`: `request_transition()` is the
general-purpose entry point (applies immediately if `AUTO_ALLOWED`,
otherwise creates a pending approval); `transition()` is the strict
entry point (applies immediately if `AUTO_ALLOWED`, otherwise always
raises — never creates a pending approval itself). `get_allowed_transitions()`
lists every structurally legal destination including gated ones;
`can_transition()` answers the narrower "would `transition()` succeed
*right now*, with no pending approval" question.

## Approval System

Built entirely on Phase 3's existing `Approval` model — no new columns.
`Approval.stage` (a plain string in Phase 3) is used as an **encoded
key**:

- A stage-transition request encodes both endpoints:
  `"STAGE_05_RESEARCH_GAP->STAGE_03_LITERATURE_SEARCH"`. `approve()`
  decodes this and applies exactly that transition.
- An administrative action encodes its name: `"ARCHIVE_PROJECT"` or
  `"REJECT_PROJECT"`.

`Approval` already carries `project_id`, `stage` (as above), `comment`,
`requested_at`, `decided_at`, and `decision` — everything the spec asks
for except **actor**, which Phase 3's `Approval` model has no column
for. Rather than add one (another schema change), the actor for every
request and every decision is recorded via a companion `AuditEvent` in
the same atomic transaction (`workflow.approval_requested`,
`workflow.approval_approved`/`_rejected`/`_changes_requested`) — Phase
3 already built `AuditEvent` to be exactly this kind of
actor-and-context ledger, so the two tables cover the spec's approval
record fields between them.

## Audit Log

Every workflow mutation — stage transition, approval request/decision,
pause/resume/archive/reject — writes an `AuditEvent` in the *same*
transaction as the mutation itself. Fields map as follows:

| Spec field | Where it lives |
|---|---|
| project ID | `AuditEvent.project_id` (FK) |
| actor | `AuditEvent.actor` |
| timestamp | `AuditEvent.created_at` |
| previous stage / new stage / transition type / reason | `AuditEvent.metadata_` (JSON: `previous_stage`, `new_stage`, `transition_type`, `reason`) |
| metadata where useful | `AuditEvent.metadata_` also carries `approval_id` when a transition was approval-driven |

`event_type` values: `workflow.transition`, `workflow.approval_requested`,
`workflow.approval_approved`, `workflow.approval_rejected`,
`workflow.approval_changes_requested`, `workflow.project_paused`,
`workflow.project_resumed`, `workflow.project_archived`,
`workflow.project_rejected`.

**Never silently changes stage:** every code path that calls
`repository.update_project(session, project_id, current_stage=...)`
is immediately followed, in the same transaction, by
`repository.append_audit_event(...)` — see `_apply_stage_transition()`
in `service.py`.

## State Consistency and Atomicity

Every orchestrated operation opens exactly one `session_scope()`
(reused from Phase 3's `researchos.db.engine`) and does all of its work
— the mutation(s) plus the audit event — inside it. `session_scope()`
commits once on clean exit and rolls back everything on any exception.
Concretely: `_apply_stage_transition()` calls
`repository.update_project()` (flushes, but doesn't commit) *then*
`repository.append_audit_event()`; if the audit event fails validation
(e.g. a blank actor), the exception propagates out of the whole
`with session_scope(...)` block, which rolls back — undoing the
already-flushed stage update too. Verified directly in
`tests/workflow/test_atomicity.py` by forcing exactly this failure with
a blank/whitespace actor and confirming the project's stage is
unchanged afterward. "If an approval is required and has not been
approved, the transition must not occur" is enforced structurally by
`transition()` never applying a gated edge without going through
`approve()` — there is no code path that checks for "an approval
happens to exist" and proceeds; `approve()` is the only writer.

## Concurrency

A basic, explicit, **optimistic** concurrency check — not distributed
locking (SQLite itself is single-writer at the file level; there is no
meaningful distributed-lock story to build here without seriously
over-engineering this phase). Callers that care can pass
`expected_current_stage=...` to `request_transition()` / `transition()`;
if the project's actual current stage no longer matches by the time the
call executes, `ConcurrentModificationError` is raised instead of
silently overwriting a decision made against stale information. Callers
that don't pass it opt out of the check entirely (unaffected, backward
compatible). See `tests/workflow/test_concurrency.py`.

## Errors

All in `researchos.workflow.errors`, all subclassing `WorkflowError`:

| Error | Raised when |
|---|---|
| `ProjectNotFoundError` | No `ResearchProject` with the given id |
| `InvalidTransitionError` | No-op, illegal forward jump, or (via policy) any non-adjacent forward move |
| `InvalidWorkflowStateError` | Unparseable `current_stage`, admin action from the wrong status, unrecognized `Approval.stage` key |
| `ApprovalRequiredError` | `transition()` called on a gated edge with no approval process completed |
| `ApprovalNotFoundError` | No `Approval` with the given id |
| `ApprovalAlreadyDecidedError` | Deciding an approval that isn't `PENDING` |
| `HumanOnlyActionError` | An agent actor attempts a `HUMAN_ONLY` request, or anyone but a human attempts to decide any approval |
| `ProjectArchivedError` | Any transition attempted on an archived project |
| `ProjectPausedError` | Any transition attempted on a paused project |
| `ProjectRejectedError` | Any transition attempted on a rejected project |
| `ConcurrentModificationError` | `expected_current_stage` doesn't match the project's actual current stage |

No error message in this package includes a secret — none of the
workflow layer's inputs are secrets (project ids, stage names, actor
labels, human-authored reasons/comments).

## Testing Strategy

`tests/workflow/` (79 tests) uses the same pattern as `tests/db/`: a
fresh temporary SQLite file per test, migrated via the real Alembic
path. No test makes a real API call, and no test uses real research
data (all titles/actors/reasons are obviously fake, e.g. "Fake Workflow
Test Project", `actor="agent:literature-bot"`).

| File | Covers |
|---|---|
| `test_stages_and_policy.py` | Pure, no-DB unit tests: all 20 stages, ordering, every forward gate's policy, backward-always-approval, actor convention |
| `test_initial_state.py` | A fresh project starts at STAGE_01 with only one allowed (gated) transition |
| `test_forward_transitions.py` | AUTO_ALLOWED edges apply immediately for any actor, via both `request_transition` and `transition` |
| `test_invalid_transitions.py` | Forward jumps, same-stage no-ops, unrecognized strings, corrupted `current_stage` values |
| `test_backward_transitions.py` | Backward moves require approval, are tagged `"backward"`, never apply without one |
| `test_approval_flow.py` | Request/approve/reject/request-changes lifecycle, already-decided guard, cross-project pending listing |
| `test_human_only.py` | Agents blocked from requesting/deciding HUMAN_ONLY and any approval decision |
| `test_atomicity.py` | Forced audit-validation failure rolls back the already-flushed stage/approval write |
| `test_project_isolation.py` | Stage, approvals, and audit events never leak across projects |
| `test_pause_resume_archive_reject.py` | Paused/archived/rejected projects block all transitions; idempotency guards |
| `test_concurrency.py` | `expected_current_stage` mismatch raises; matching/omitted cases succeed |
| `test_audit_log.py` | Every event type's exact field content (actor, metadata, transition_type, reason) |

Run with:
```powershell
<repository-root>\.venv\Scripts\python.exe -m pytest tests\workflow -v
```

## Examples

```python
from researchos import workflow
from researchos.db import repository
from researchos.db.engine import session_scope

# Create a project (Phase 3 API — unchanged).
with session_scope() as session:
    project = repository.create_project(session, title="Does X affect Y?")
    project_id = project.id

# It starts at STAGE_01_IDEA implicitly.
with session_scope() as session:
    assert workflow.get_current_stage(session, project_id) == workflow.WorkflowStage.STAGE_01_IDEA

# Accepting the idea requires approval (gate #1).
outcome = workflow.request_transition(
    project_id, workflow.WorkflowStage.STAGE_02_INITIAL_VALIDATION,
    actor="agent:idea-scout", reason="initial validation looks promising",
)
assert not outcome.applied  # pending, nothing changed yet

decided = workflow.approve(outcome.approval.id, actor="user:pi", comment="agreed")
# Now current_stage == STAGE_02_INITIAL_VALIDATION.

# Literature search/mapping/gap-identification are AUTO_ALLOWED.
workflow.request_transition(project_id, workflow.WorkflowStage.STAGE_03_LITERATURE_SEARCH, actor="agent:lit-bot")

# An agent can never even request the final, HUMAN_ONLY publication step.
try:
    workflow.request_transition(project_id, workflow.WorkflowStage.STAGE_20_FINAL, actor="agent:manuscript-bot")
except workflow.HumanOnlyActionError:
    pass  # expected
```

## What Is Intentionally NOT Implemented Yet

- No research agents — nothing in this phase decides *what* to
  research, only whether a proposed state change is authorized.
- No literature search, novelty analysis, dataset analysis, or
  experiment execution.
- No manuscript generation.
- No dashboard/UI/API surface exposing any of this over HTTP.
- No real identity/authentication system — the `"agent:"` prefix
  convention is an explicit, documented placeholder.
- No automatic linkage between reaching `STAGE_20_FINAL` and
  `ProjectStatus.COMPLETED` — nothing in this phase sets `COMPLETED`.
- No retrofit of the `CHECK`-constraint gap found in Phase 3's other 13
  enum columns (see above) — flagged, not fixed, pending your direction.
- No real LLM/external API calls anywhere in this phase.
