# Development and validation

The `Validation` GitHub Actions workflow runs Python tests and examples on Linux and Windows, and frontend lint/type checks, unit tests, build and the Chromium smoke test on Linux. It uses read-only repository permissions and pinned action commits; no provider credentials are required. Consult the actual run status before claiming checks passed. Python dependency ranges remain unlocked; this workflow is not a hermetic environment lock.

Start with the root README's virtual environment and editable install. Include both `dev` and `dashboard` extras to run the full Python suite. Tests cover domain services, temporary SQLite migrations, mock LLM/source adapters, security boundaries, subprocess execution, and the dashboard API.

Windows CI partitions the complete pytest collection into four jobs to stay within the job timeout. Linux runs the full collection in one job. The runner sorts test IDs and assigns every fourth test to a shard, automatically including new tests. To reproduce one Windows partition locally, run `python scripts/run_test_shard.py 0 4 -q` (indices 0 through 3); use the normal pytest command below for the full suite.

Run `python -m pytest tests -q` from the repository root. Some platform-dependent tests may skip; report skipped cases rather than claiming they passed. Python linting, formatting, and static type checking are not currently configured. Do not describe import checks or pytest as substitutes for them.

In `apps/dashboard/frontend`, run `npm ci`, `npm run lint`, `npm run typecheck`, `npm test`, and `npm run build`. The lockfile controls the npm dependency graph. Install Chromium using `npx playwright install chromium`, then run `npm run test:e2e`. The launcher expects `.venv` at the repository root. It uses explicitly synthetic seed records and ports 8000/4300. Never point tests at a private research database.

No formatter is configured. Avoid repository-wide reformatting unrelated to a change. Python requirements are ranges; record installed versions when reporting reproducibility and test results. Live API compatibility, current provider model availability, scientific validity, and production deployment are outside the automated suite's guarantees.

For schema changes, add an Alembic migration and migration regression coverage. Back up local data before running migrations. Do not edit applied historical migrations to hide schema changes.
