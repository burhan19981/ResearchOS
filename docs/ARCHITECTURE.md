# Architecture

ResearchOS separates persistence, domain operations, external provider adapters, and a local dashboard.

`db` owns SQLAlchemy models and repository operations. Alembic migrations are the schema source of truth. `workflow` models stage transitions and approvals. Human/agent actor labels express workflow policy but are not an authentication system.

`evidence` retrieves and normalizes source metadata and links evidence to records. `llm` abstracts providers. `intelligence` generates literature, gap, and novelty candidates; `planning` develops questions, contributions, methodology, dataset requirements, and experimental design; `specification` records dataset versions and experiment specifications. Generated artifacts require review; model output is not proof of a scientific claim.

`execution` connects approved specifications to run requests, preflight validation, a local subprocess executor, artifacts, metrics, and provenance. Module/executable allowlists fail closed until configured. This is invocation control, not a sandbox. `analysis` links results to claims and scientific review records.

`apps/dashboard/api` adapts these services to FastAPI. `apps/dashboard/frontend` uses React, TanStack Query, and React Router to inspect records and submit approval decisions. The UI does not launch experiments or LLM generation.

The library currently expects a source checkout for migrations and configuration. SQLite is the development/test database. Other SQLAlchemy URLs are accepted by configuration, but production database portability has not been established. Consult the `PHASE*.md` documents for historical implementation details; their original test totals and implementation-time observations are not current validation claims.
