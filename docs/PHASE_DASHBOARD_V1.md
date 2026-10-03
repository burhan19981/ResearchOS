> Historical implementation notes. For current setup, status, and security boundaries, see [the README](../README.md) and [SECURITY.md](../SECURITY.md). Historical test counts describe earlier development checkpoints.

# Dashboard V1

Date: 2026-09-18
Scope: a UI/control layer over the existing ResearchOS backend — a
FastAPI API (`apps/dashboard/api/researchos_api/`) that exposes the
already-implemented domain services as stable JSON contracts, and a
React/TypeScript frontend (`apps/dashboard/frontend/`) that visualizes
and drives them. This phase implements no new domain logic, no new
research-workflow behavior, and no new scientific semantics — every
number, status, and approval decision the dashboard shows comes
directly from `researchos.*` under `src/`, reused as-is.

## Architecture

```
React Dashboard (Vite, TypeScript)
        │  HTTP/JSON, relative /api/v1/*
        ▼
FastAPI API (apps/dashboard/api/researchos_api/)
        │  routers/ -> thin handlers, no business logic
        │  schemas/ -> explicit Pydantic response contracts
        │  services/mapping.py -> ORM -> schema field mapping only
        │  services/approvals.py -> stage-prefix dispatch table
        ▼
Existing ResearchOS domain services
  researchos.db.repository (reads)
  researchos.{intelligence,planning,specification,execution,analysis}.approval (writes)
  researchos.workflow.service (pipeline state + workflow-stage approvals)
        │
        ▼
Existing SQLAlchemy 2.x repository layer
        │
        ▼
Existing SQLite database (DATABASE_URL, unchanged) — no second database
```

The API layer is deliberately thin: every `GET` route calls a
`researchos.db.repository.list_*`/`get_*` function and maps the ORM
result onto a Pydantic schema (`services/mapping.py`) — no filtering,
sorting, or status logic lives in the API layer beyond field selection.
The one mutating route, `POST /projects/{id}/approvals/{id}/actions`,
dispatches to the exactly one existing domain
`approve_*`/`reject_*`/`request_changes_*` function for that approval's
stage (`services/approvals.py`'s dispatch table) — it never
reimplements an approval rule.

## Frontend Stack

React 19 + TypeScript + Vite 8, React Router 7 (client-side routing),
TanStack Query 5 (server state — caching, invalidation, loading/error
states), Tailwind CSS 4 (via `@tailwindcss/vite`, CSS-first `@theme`
configuration — no separate `tailwind.config.js`), Lucide React (icons),
Recharts (charts, not used in V1's list/table-oriented pages — kept as
a dependency for V2's metric visualizations). Vitest + React Testing
Library for component tests; Playwright for one end-to-end smoke test.

A clean, dark-oriented engineering/research visual language
(`src/index.css`'s `@theme` block) — no gradients, no decorative
illustrations, no "AI" shimmer effects. Status is always communicated
via icon + text + color together (`StatusPill`), never color alone.

## API Structure

```
apps/dashboard/api/researchos_api/
  main.py            FastAPI app; CORS (localhost:5173 dev origin only);
                      mounts every router under /api/v1; OpenAPI at
                      /api/v1/openapi.json, docs at /api/v1/docs
  dependencies.py    get_db (request-scoped Session), get_session_factory
                      (injectable — see Testing below), get_project_or_404
                      (the project-isolation checkpoint), DASHBOARD_ACTOR
  errors.py          One exception handler per domain layer's own base
                      error class (DatabaseError, PlanningError,
                      WorkflowError, AnalysisError, ExecutionError,
                      SpecificationError, IntelligenceError) — maps to
                      404/403/409/400 by subclass name; a catch-all
                      500 handler never leaks a Python traceback.
  schemas/           Explicit Pydantic response models — no SQLAlchemy
                      ORM object is ever returned directly as JSON.
  services/
    mapping.py        ORM -> schema conversion (evidence counts, nested
                      artifacts/metrics/reviews, cited-question ids)
    approvals.py       The stage-prefix -> domain-function dispatch
                      table (13 layers: intelligence/planning/
                      specification/execution/analysis approvals plus
                      workflow-stage transitions)
  routers/           One thin router per resource area
```

## Routes (Backend)

```
GET  /api/v1/health
GET  /api/v1/projects
GET  /api/v1/projects/{project_id}
GET  /api/v1/projects/{project_id}/overview
GET  /api/v1/projects/{project_id}/pipeline
GET  /api/v1/projects/{project_id}/literature   [?q=&source=&evidence_status=]
GET  /api/v1/projects/{project_id}/gaps
GET  /api/v1/projects/{project_id}/novelty
GET  /api/v1/projects/{project_id}/planning
GET  /api/v1/projects/{project_id}/experiments
GET  /api/v1/projects/{project_id}/experiments/{experiment_id}
GET  /api/v1/projects/{project_id}/runs         [?experiment_id=]
GET  /api/v1/projects/{project_id}/runs/{run_id}
GET  /api/v1/projects/{project_id}/analysis
GET  /api/v1/projects/{project_id}/reviews
GET  /api/v1/projects/{project_id}/approvals
POST /api/v1/projects/{project_id}/approvals/{approval_id}/actions
GET  /api/v1/projects/{project_id}/audit
```

No `/execute_sql`, `/run_command`, `/eval`, or any generic
database/shell-access endpoint exists.

## Frontend Routes

```
/dashboard                              Overview (uses the selected project)
/dashboard/projects/:projectId          Overview for an explicit project id (deep link; syncs the selector)
/dashboard/pipeline                     Research Pipeline visualization
/dashboard/evidence                     Literature (search/filter client-side over the project's list)
/dashboard/evidence/gaps                Research Gaps
/dashboard/evidence/novelty             Novelty Assessments
/dashboard/planning                     Research planning traceability chain
/dashboard/experiments                  Experiments list
/dashboard/experiments/:experimentId    Experiment detail + its Runs
/dashboard/experiments/runs/:runId      Run detail (config, environment, artifacts, metrics)
/dashboard/analysis                     Analysis records (comparisons/aggregations/rankings)
/dashboard/analysis/reviews             Scientific Claims + their Reviews
/dashboard/approvals                    Approval Center
/dashboard/audit                        Audit Log
```

Every one of the spec's seven minimum-required routes is present;
Evidence/Gaps/Novelty and Analysis/Reviews are combined feature areas
with nested routes and sidebar entries rather than one page each,
matching the spec's explicit "combine pages" allowance.

## Project Isolation

Every project-scoped route depends on `get_project_or_404`, which
looks up the path's `project_id` in the database before any
route-specific logic runs — a nonexistent project id 404s uniformly,
and a record belonging to a different project is never returned (every
`list_*`/`get_*` repository call is itself already project-scoped by
`project_id`, and `get_experiment`/`get_run` handlers additionally
check `row.project_id == project.id` before returning). The Approval
Center's action endpoint checks `approval.project_id == project_id`
before dispatching a decision — acting on another project's approval
through the "wrong" project's URL 404s rather than silently applying
cross-project. See `tests/dashboard_api/` for the isolation tests this
guarantees.

The frontend never sends a project id the user didn't select: the
top-bar `ProjectSelector` is the single source of truth
(`ProjectContext`, persisted to `localStorage` for convenience only —
never trusted as authorization), and every query key includes the
project id so switching projects never serves stale cross-project data
from the TanStack Query cache.

## Approval Flow

`researchos.db.repository.list_approvals` already returns every
`Approval` row for a project across all 13 approval-capable layers —
the API's `GET /approvals` calls it once and parses each row's `stage`
string (`"<PREFIX>:<entity_id>"`, or a workflow transition key
`"<FROM>-><TO>"`, or `"ARCHIVE_PROJECT"`/`"REJECT_PROJECT"`) to report
a human-readable `entity_type`/`entity_id` for display.

`POST /approvals/{id}/actions` accepts `{"action": "approve" |
"reject" | "request_changes", "comment": string | null}` — **no
actor/identity field exists in this contract at all**. The server
always records the fixed, non-agent actor string
`dependencies.DASHBOARD_ACTOR = "user:dashboard"`
(`researchos.workflow.policy.is_human_actor` treats any string not
starting with `"agent:"` as human) — Dashboard V1 has no real
authentication system, and a client-supplied `actor`/`is_human` field
would be trivially forgeable, so none is ever read from the request.
`tests/dashboard_api/test_approvals.py::
test_client_supplied_actor_field_is_ignored_not_trusted` verifies extra
fields sent by a malicious client have zero effect.

Every precondition a domain approval function enforces (a
`ScientificReview` must be `READY_FOR_HUMAN_REVIEW` before it can be
approved; a `ScientificClaim` needs a `HUMAN_APPROVED` review behind
it; a `DatasetVersion` must be `VALID`; an agent actor can never
decide) is enforced by that function itself — the dispatch table in
`services/approvals.py` only routes the call, and a violated
precondition surfaces as a structured 400 (`ReviewNotReadyError`,
`ClaimNotSupportedByApprovedReviewError`, ...) via `errors.py`, never
silently succeeding.

A read-then-mutate-then-reread session-staleness bug was found and
fixed during implementation: the request-scoped `Session` used to list
approvals already had the target `Approval` row cached in its identity
map before the mutation (which commits through the domain function's
*own*, separate session) — with `expire_on_commit=False`, a naive
re-`get()` on that same session would silently return the
pre-decision snapshot. `act_on_approval` calls `session.rollback()`
(safe — that session made no writes of its own) before re-reading, so
`ApprovalActionResponse.entity_status` always reflects the just-committed
decision.

## Testing

**Backend** (`tests/dashboard_api/`, pytest, mirrors the
`tests/execution`/`tests/analysis` fixture-chain pattern — a fresh
temporary SQLite database per test, migrated via the real Alembic
path): 42 tests across health/projects, project isolation, overview,
pipeline, literature/gaps/novelty, experiments/runs, analysis/reviews,
planning, the Approval Center (dispatch across every layer, human-only
enforcement, cross-project rejection, already-decided conflicts,
malformed-action validation, the client-actor-ignored guarantee, and a
full two-step scientific-review-then-claim approval chain), and audit.
`researchos_api` is not pip-installed; `tests/dashboard_api/conftest.py`
adds `apps/dashboard/api` to `sys.path` directly.

**Frontend** (Vitest + React Testing Library, `npm test`): 39 tests —
`apiClient` (success/structured-error/non-JSON-error/POST-body
shape), `format`/`statusTone` pure-function units, `StatusPill`
(icon+text+color, never color alone), `LoadingState`/`EmptyState`/
`ErrorState` (including "never renders a raw stack trace"),
`ProjectSelector` (default selection, switching), full `App` boot +
sidebar navigation + honest-zero-counts + error-state, `PipelinePage`
rendering, `AuditPage` rendering (including ordering), and
`ApprovalsPage`'s full interaction (dialog open, decision required
before submit, successful submission showing the server's actual
resulting status, and the actor-spoofing-is-ignored test). Two
non-obvious fixtures gotchas were found and fixed while writing these:
(1) a shared/module-singleton `queryClient` (imported directly by
`App.tsx`) caches query results *across tests in the same file*
(15s `staleTime`) — `queryClient.clear()` in `beforeEach` is required
whenever a test renders `<App />` directly; (2) `BrowserRouter`'s
history is backed by the real jsdom `window`, which Vitest does not
reset between tests in one file — an earlier navigation test's
`pushState` leaks into later tests unless the URL is reset in
`beforeEach`.

**End-to-end** (Playwright, `npm run test:e2e`): one smoke test
(`e2e/dashboard.spec.ts`) exercising the real backend (seeded via
`apps/dashboard/api/e2e_seed_and_serve.py` — an isolated, temporary
SQLite database with one small, obviously-synthetic project, deleted
on process exit) and the real production frontend build together:
open dashboard → project loads → Pipeline → Experiments → experiment
detail → Run detail → Approval Center → open the review dialog →
Overview. `playwright.config.ts` starts both servers itself
(`webServer` array) — the frontend's `vite preview` proxies `/api` to
the backend on `:8000` (mirroring the dev-server proxy), so the browser
never needs CORS for this flow.

## Local Development

```bash
# Backend (from repo root, with the existing .venv active)
pip install -e ".[dashboard]"
uvicorn researchos_api.main:app --app-dir apps/dashboard/api --reload --port 8000

# Frontend (separate terminal)
cd apps/dashboard/frontend
npm install
npm run dev            # http://localhost:5173, proxies /api to :8000
```

## Build / Test / Lint Commands

```bash
# Backend
pytest tests/dashboard_api -q              # dashboard API tests
pytest -q                                  # full existing suite (must stay green)

# Frontend (from apps/dashboard/frontend)
npm run typecheck                          # tsc -b --noEmit
npm run build                              # tsc -b && vite build (production bundle)
npm run lint                               # oxlint
npm test                                   # vitest run
npm run test:e2e                           # playwright test (starts both servers itself)
```

## Known Limitations

- **No authentication/authorization system.** Every approval decision
  is recorded under one fixed actor string
  (`dependencies.DASHBOARD_ACTOR`); there is no concept of distinct
  human users, sessions, or per-user permissions in V1. This is
  explicitly out of scope for V1 per the task's own framing ("PI"
  label in the top bar is a static placeholder, not a real identity).
- **CORS is permissive for localhost only**, intended for local
  development; a real deployment would need a proper origin allowlist
  and likely authentication in front of the mutating endpoint.
- **No pagination.** `list_*` endpoints return every row for a
  project; acceptable at this project's current data scale, but would
  need pagination before a project accumulates thousands of literature
  items/runs/audit events.
- **No real-time updates.** The dashboard is pull-based (TanStack
  Query refetch/invalidation); a Run transitioning from `RUNNING` to
  `SUCCEEDED` elsewhere is not pushed to an open browser tab — the user
  must navigate or the relevant query must become stale and refetch.
- **No generation/creation actions.** Dashboard V1 is read + approve
  only — it cannot create a research question, launch a run, or
  trigger any LLM-assisted generation service; those remain
  script/API-only until a future phase decides whether the dashboard
  should expose them.
- **Chart library (Recharts) is installed but unused in V1** — every
  V1 page uses tables/cards, which suit this phase's list-oriented,
  small-N data better than a chart; left in place for V2's metric
  visualizations rather than removed and re-added.

## Dashboard V2 Boundaries (explicitly out of scope for V1)

No manuscript generation, no citation formatting/audit engine, no
journal matching, no submission system, no peer review engine, no
in-dashboard AI chat, and no domain-specific (PPE/FastViT/RetinaNet/
YOLO or otherwise) logic anywhere in the dashboard — V1 is a read
surface plus the one existing approval mechanism, nothing more. Real
authentication, pagination, real-time updates, and any create/generate
action are left for a future phase to scope deliberately, not implied
by anything built here.
