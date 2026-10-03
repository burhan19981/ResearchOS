> Historical implementation notes. For current setup, status, and security boundaries, see [the README](../README.md) and [SECURITY.md](../SECURITY.md). Historical test counts describe earlier development checkpoints.

# Phase 3: Persistent Research State and Database

Date: 2026-09-17
Scope: A persistent state layer for ResearchOS — SQLite via SQLAlchemy
2.0, Alembic migrations, and a repository layer covering all 14 entities
from the Phase 3 spec. No workflow engine, agents, literature search, or
dashboard were built. No real LLM API calls were made and no real
research data was used — every test runs against a throwaway temporary
SQLite file.

## Database Architecture

```
src/researchos/db/
├── __init__.py       # Public API — import from here for common needs
├── config.py          # DATABASE_URL / echo-flag loading (+ .env support)
├── engine.py           # Engine, session factory, session_scope()
├── models.py            # ORM models: Base, mixins, enums, all 14 entities
├── errors.py             # Normalized exceptions (NotFoundError, etc.)
├── repository.py          # Persistence operations — no raw SQL for callers
└── migrate.py               # init_db() — programmatic `alembic upgrade head`

alembic.ini             # Alembic config (script_location, logging)
migrations/
├── env.py               # Alembic environment — targets Base.metadata
├── script.py.mako         # Revision file template
└── versions/
    └── <rev>_initial_schema.py   # The initial migration (all 14 tables)
```

**Technology choice:** SQLite for local development today, via
**SQLAlchemy 2.0** (the ORM) and **Alembic 1.20** (migrations). Nothing
in `models.py`, `repository.py`, or `engine.py` is SQLite-specific
except one explicitly-isolated helper
(`engine._enable_sqlite_foreign_keys`, gated on the URL scheme) — see
"Future PostgreSQL Migration" below for exactly what changes and what
does not.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Any SQLAlchemy connection URL | `sqlite:///<repo_root>/data/researchos.db` |
| `RESEARCHOS_DB_ECHO` | Log every SQL statement (debugging) | `false` |

The default database file lives at `data/researchos.db` — outside
`src/`, alongside the `data/raw/` and `data/processed/` directories
from Phase 1 — and is created automatically (including its parent
directory) on first use. It is gitignored (`*.db`, `*.sqlite*`, and
`data/researchos.db` explicitly) and must never be committed, since a
real deployment's database is local runtime state, not source code.

Configuration is loaded the same way as Phase 2's LLM provider config:
`researchos.db.config.load_database_config()` reads `DATABASE_URL` from
the environment (optionally populated from a local `.env`, never
committed) with `load_dotenv(..., override=False)` so real environment
variables always win.

## Schema

All 14 entities from the Phase 3 spec are implemented in
`src/researchos/db/models.py`:

`ResearchProject`, `ResearchIdea`, `ResearchQuestion`, `LiteratureItem`,
`ResearchGap`, `NoveltyAssessment`, `MethodologyPlan`, `DatasetRecord`,
`Experiment`, `ExperimentResult`, `Manuscript`, `JournalCandidate`,
`Approval`, `AuditEvent`.

### Design decisions

- **Primary keys:** every table has an integer autoincrement `id`.
  This maps to `INTEGER PRIMARY KEY` on SQLite and `SERIAL`/`IDENTITY`
  on PostgreSQL with no code change.
- **Status vocabularies are Python `str` enums** (`ProjectStatus`,
  `IdeaStatus`, `QuestionStatus`, `EvidenceStatus`, `GapStatus`,
  `NoveltyStatus`, `MethodologyStatus`, `ExperimentStatus`,
  `ManuscriptStatus`, `JournalCandidateStatus`, `ApprovalDecision`),
  mapped via SQLAlchemy's `Enum(..., native_enum=False, length=32)`.
  `native_enum=False` renders as a plain `VARCHAR` + `CHECK` constraint
  on **every** backend — including a future PostgreSQL — rather than a
  PostgreSQL-native `CREATE TYPE`. This means adding a new status value
  later is a migration that alters a `CHECK` constraint, never an
  `ALTER TYPE ... ADD VALUE` with its PostgreSQL-specific transaction
  restrictions.
- **Free-form vocabulary fields with no approved fixed set** —
  `ResearchProject.current_stage`, `ResearchQuestion.type`,
  `LiteratureItem.source`, `Approval.stage` — are plain strings, not
  enums. These are conceptually tied to a future workflow engine that
  this phase explicitly does not build; constraining them now would be
  guessing at an unapproved vocabulary.
- **Structured metadata** (`Experiment.configuration`,
  `ExperimentResult.metadata`, `AuditEvent.metadata`,
  `DatasetRecord.split_information`) uses SQLAlchemy's `JSON` type,
  which serializes/deserializes safely (parameterized, never
  string-concatenated) on every backend.
- **The `metadata` naming collision:** `metadata` is a reserved
  attribute name on every SQLAlchemy declarative model (it holds the
  table's `MetaData` object), so the Python attribute for the
  `ExperimentResult`/`AuditEvent` "metadata" column is named
  `metadata_` and mapped to the actual database column `"metadata"`
  via `mapped_column("metadata", JSON, ...)`. The repository functions
  (`record_experiment_result`, `append_audit_event`) still accept a
  `metadata=` keyword argument, so this is invisible to callers.
- **Validation** (`@validates` methods) enforces: non-blank required
  text fields (titles, statements, claims, etc.), confidence values in
  `[0.0, 1.0]` (`ResearchGap.confidence`, `NoveltyAssessment.confidence`),
  finite `ExperimentResult.metric_value` (rejects `NaN`/`inf`),
  non-negative `LiteratureItem.year`, and positive integer version
  numbers (`MethodologyPlan.version`, `Manuscript.version`). These
  raise `researchos.db.errors.ValidationError` immediately on
  attribute assignment — before anything reaches the database.

### Indexes and uniqueness constraints

- Every foreign key column (`project_id`, `experiment_id`) is indexed.
- `AuditEvent.event_type` and `ExperimentResult.metric_name` are
  indexed for common filtering.
- Unique constraints: `(project_id, doi)` on `literature_items` (NULLs
  are exempt — a project can have any number of literature items with
  no DOI, matching normal SQL NULL semantics); `(project_id, version)`
  on `methodology_plans` and `manuscripts`; `(project_id, name,
  version)` on `dataset_records`.
- **Deliberately no** uniqueness constraint on `(experiment_id,
  metric_name)` in `experiment_results`: repeated measurements of the
  same metric (e.g. per-epoch loss) are a legitimate, expected use
  case, not a data-integrity violation. See
  `tests/db/test_repository_experiments.py::test_multiple_results_with_same_metric_name_are_allowed`.

## Relationships

```
ResearchProject
├── ResearchIdea            (project_id, CASCADE)
├── ResearchQuestion        (project_id, CASCADE)
├── LiteratureItem          (project_id, CASCADE)
├── ResearchGap             (project_id, CASCADE)
├── NoveltyAssessment       (project_id, CASCADE)
├── MethodologyPlan         (project_id, CASCADE)
├── DatasetRecord           (project_id, CASCADE)
├── Experiment              (project_id, CASCADE)
│      └── ExperimentResult (experiment_id, CASCADE)
├── Manuscript              (project_id, CASCADE)
├── JournalCandidate        (project_id, CASCADE)
├── Approval                (project_id, CASCADE)
└── AuditEvent              (project_id, CASCADE)
```

Every child foreign key is declared `ondelete="CASCADE"` at the
database level and `cascade="all, delete-orphan"` on the ORM
relationship, so deleting a `ResearchProject` (or an `Experiment`, for
its `ExperimentResult` rows) deletes everything beneath it — matching
the ownership tree in the Phase 3 spec. This is exercised end-to-end in
`tests/db/test_integrity_and_isolation.py::test_deleting_project_cascades_to_every_child_type`.

## Data Integrity

Two independent layers of protection against orphan/invalid records:

1. **Application layer:** every repository function that creates a
   child record looks up its parent first (`_get_project_or_raise`,
   `_get_experiment_or_raise`) and raises
   `researchos.db.errors.NotFoundError` immediately if the parent
   doesn't exist — before any DB write is attempted.
2. **Database layer:** SQLite's foreign-key enforcement is explicitly
   turned on per-connection (`PRAGMA foreign_keys=ON`, set in
   `engine._enable_sqlite_foreign_keys` — SQLite ships with this off by
   default for backward compatibility). This is a genuine second line
   of defense, not just a formality: `tests/db/test_integrity_and_isolation.py::test_database_itself_rejects_orphan_child_via_foreign_key_pragma`
   bypasses the repository layer entirely (constructs an ORM object and
   flushes it directly) and confirms the raw `IntegrityError` still
   fires.

`sqlalchemy.exc.IntegrityError` (constraint violations reaching the
database — uniqueness, NOT NULL, foreign key) is caught centrally in
`repository._flush()` and re-raised as
`researchos.db.errors.IntegrityConstraintError` with a rollback of the
current statement, so callers only ever need to handle
`researchos.db.errors.*`, never a raw driver exception.

## Repository Layer

`src/researchos/db/repository.py` provides persistence-only functions
for every entity — no raw SQL required by callers, and no workflow
decisions made anywhere in this layer:

| Entity | Functions |
|---|---|
| ResearchProject | `create_project`, `get_project`, `update_project`, `list_projects` |
| ResearchIdea | `create_research_idea`, `get_research_idea`, `list_research_ideas`, `update_research_idea` |
| ResearchQuestion | `create_research_question`, `get_research_question`, `list_research_questions` |
| LiteratureItem | `add_literature_item`, `get_literature_item`, `list_literature_items` |
| ResearchGap | `record_research_gap`, `get_research_gap`, `list_research_gaps`, `update_research_gap` |
| NoveltyAssessment | `record_novelty_assessment`, `get_novelty_assessment`, `list_novelty_assessments` |
| MethodologyPlan | `create_methodology_version` (auto-increments per project), `get_methodology_plan`, `list_methodology_plans` |
| DatasetRecord | `register_dataset`, `get_dataset`, `list_datasets` |
| Experiment | `register_experiment`, `get_experiment`, `list_experiments`, `start_experiment`, `complete_experiment` |
| ExperimentResult | `record_experiment_result`, `get_experiment_result`, `list_experiment_results` |
| Manuscript | `create_manuscript` (auto-increments version per project), `get_manuscript`, `list_manuscripts`, `update_manuscript` |
| JournalCandidate | `create_journal_candidate`, `get_journal_candidate`, `list_journal_candidates` |
| Approval | `create_approval_request`, `record_approval_decision`, `get_approval`, `list_approvals` |
| AuditEvent | `append_audit_event`, `get_audit_event`, `list_audit_events` |

**Transaction model:** every repository function takes an explicit
`Session` supplied by the caller and only `flush()`es (populating
autogenerated ids/timestamps and surfacing integrity errors
immediately) — it never commits. Commit/rollback is the caller's
responsibility via `researchos.db.engine.session_scope()`:

```python
from researchos.db import repository
from researchos.db.engine import session_scope

with session_scope() as session:
    project = repository.create_project(session, title="My Project")
    repository.append_audit_event(
        session, project_id=project.id, event_type="project_created", actor="system"
    )
# both committed together, or both rolled back together if anything raises
```

This explicit-session design (rather than hidden global session state)
is what makes atomic multi-step transactions and their rollback
behavior straightforward to test — see `tests/db/test_engine_and_transactions.py`.

## Migrations

**Alembic is the single source of truth for the schema.** There is no
separate "quick create" path that could drift from the tracked
migrations: `researchos.db.migrate.init_db()` simply runs `alembic
upgrade head` programmatically against the resolved database URL.

- `migrations/env.py` targets `researchos.db.models.Base.metadata` and
  resolves its own database URL from `researchos.db.config` (so a bare
  `alembic upgrade head` / `alembic revision --autogenerate` on the
  command line uses the same `DATABASE_URL` resolution as the
  application). `init_db(database_url=...)` temporarily sets the
  `DATABASE_URL` environment variable for the duration of the call so
  an explicit override reaches `env.py`, then restores whatever was
  there before.
- `render_as_batch=True` is set for both online and offline migration
  modes — required for SQLite, which cannot `ALTER` most column
  constraints in place (Alembic instead rebuilds the table under the
  hood); a no-op on PostgreSQL.
- The initial migration
  (`migrations/versions/8eba82f8bdd1_initial_schema.py`) was generated
  with `alembic revision --autogenerate` against the real ORM models
  (not hand-written), then verified by running `alembic upgrade head`
  followed by `alembic downgrade base` followed by `alembic upgrade
  head` again against a scratch database — both directions apply
  cleanly.

```powershell
# Bring a fresh (or existing) database up to date:
$env:DATABASE_URL = "sqlite:///data/researchos.db"   # or omit for the default
<repository-root>\.venv\Scripts\python.exe -m alembic upgrade head

# Or programmatically:
python -c "from researchos.db.migrate import init_db; init_db()"

# Create a new migration after changing models.py:
<repository-root>\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe the change"
```

## Testing

`tests/db/` (71 tests) uses a fresh temporary SQLite file per test
(pytest's `tmp_path`), brought up to schema via the **real** Alembic
migration path (`init_db()`), not a `create_all()` shortcut — so the
migration itself is exercised on every test run, not just once
manually. No test ever touches the developer's real
`data/researchos.db`, and no real research data appears anywhere in
the test suite (all titles/claims/metrics are clearly fake, e.g. "Fake
Research Project").

| File | Covers |
|---|---|
| `test_migrations.py` | Fresh DB init, idempotency, missing-parent-directory creation, current revision, FK presence |
| `test_config.py` | `DATABASE_URL` default/override, PostgreSQL-URL passthrough, echo flag |
| `test_engine_and_transactions.py` | `session_scope` commit/rollback, atomic multi-step rollback, integrity-error rollback recovery, engine singleton behavior |
| `test_validation.py` | Every `@validates` rule (blank fields, confidence bounds, non-finite metrics, version bounds) |
| `test_repository_project.py` | Project CRUD, timestamp behavior (`created_at` immutable, `updated_at` advances) |
| `test_repository_child_entities.py` | Ideas, questions, literature (+ DOI uniqueness scoped per project), gaps, novelty, methodology versioning (+ per-project scoping), datasets |
| `test_repository_experiments.py` | Experiment lifecycle (`start_experiment`/`complete_experiment`), repeated-metric logging, cascade delete of results |
| `test_repository_manuscripts_journals_approvals_audit.py` | Manuscript versioning, journal candidates, approval request/decision lifecycle, audit events |
| `test_integrity_and_isolation.py` | Orphan prevention (application layer + raw DB FK enforcement), full-tree cascade delete, project isolation across every child type |
| `test_serialization.py` | JSON round-trips (`configuration`, `metadata`, `split_information`) through a *different* session than the one that wrote them |

Run with:

```powershell
<repository-root>\.venv\Scripts\python.exe -m pytest tests\db -v
```

## Security

- **No API keys or secrets are ever stored in the database.** The
  schema has no column intended for credentials; `AuditEvent`'s
  `metadata`/`description` fields are documented in
  `repository.append_audit_event()`'s docstring as being for
  research-workflow provenance only — callers must not put secrets
  there, and nothing in this layer redacts audit content the way
  Phase 2's LLM layer redacts API keys.
- **No sensitive configuration is logged.** `RESEARCHOS_DB_ECHO` logs
  SQL statements/parameters (which could include research content, not
  secrets) and defaults to `false`; it is documented as a local
  debugging aid, not something to enable in a shared environment.
- **The database path/URL is fully configurable** via `DATABASE_URL`,
  never hard-coded, consistent with how Phase 2 handles provider
  credentials.

## Future PostgreSQL Migration Considerations

Switching `DATABASE_URL` to a `postgresql+psycopg://...` URL requires:

1. **Install a PostgreSQL driver** (e.g. `psycopg[binary]`) — not
   included in Phase 3's dependencies, since only SQLite is used today.
2. **Nothing in `models.py` changes.** Enums are already
   backend-neutral (`native_enum=False`); JSON columns map to
   PostgreSQL's `JSON`/`JSONB` automatically; integer autoincrement
   primary keys map to `SERIAL`/`IDENTITY` automatically.
3. **`engine._enable_sqlite_foreign_keys` simply won't fire** — it's
   gated on `resolved_url.startswith("sqlite")` — because PostgreSQL
   enforces foreign keys by default; no equivalent setup is needed.
4. **`render_as_batch=True` in `migrations/env.py` becomes a no-op** on
   PostgreSQL (it's a SQLite-only workaround for in-place `ALTER`
   limitations) — no change needed, just no longer load-bearing.
5. **Re-run `alembic upgrade head` against the new URL** — the same
   migration file applies; Alembic tracks its own
   `alembic_version` table per database.
6. **Consider `JSON` → `JSONB`** for the four structured-metadata
   columns if PostgreSQL-side JSON querying/indexing becomes valuable
   later — this would be a small, isolated follow-up migration, not a
   redesign.
7. **Connection pooling** — SQLAlchemy's default pooling differs
   sensibly per-dialect already; no code in this repository assumes
   SQLite's single-writer characteristics.

No application code, repository function, or test in this phase
assumes SQLite-only behavior except the one explicitly-gated PRAGMA
call above.

## What Is Intentionally NOT Implemented Yet

- No workflow engine — no automatic stage transitions, no logic that
  decides what happens after an approval or an experiment completes.
- No research agents, no LLM calls anywhere in this layer.
- No literature search / external data ingestion.
- No dashboard or API surface exposing this data over HTTP.
- No PostgreSQL driver installed or PostgreSQL migration executed —
  only documented as a configuration change (above).
- No soft-delete/versioning of the records themselves beyond the
  explicit version-numbered entities (`MethodologyPlan`, `Manuscript`).
- No full-text search or vector search over `LiteratureItem.abstract`.
- No real research data anywhere — every test uses obviously
  placeholder content.
