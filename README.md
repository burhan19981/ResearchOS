# ResearchOS

ResearchOS is an experimental, local research workflow platform for developers building tools that connect literature evidence, research planning, human review, and experiment provenance.

Research workflows often split evidence, decisions, experiment settings, and results across separate scripts and documents. ResearchOS provides a shared database and explicit domain services for linking those records, with human approval steps and an inspection dashboard. It is intended as a foundation for research tooling; generated suggestions are not validated scientific findings.

## Status

Early development (Python package version 0.0.1). The repository includes implemented services and automated tests, but has no demonstrated external adoption or validated research impact. APIs and schemas may change. It is not a production service or a complete autonomous research agent.

**Run the dashboard only on a trusted local machine. It has no authentication or user authorization, and approval actions use a fixed actor. The local executor runs trusted Python code with your operating-system permissions; it is not a sandbox.** See [security guidance](SECURITY.md).

## Implemented components

- SQLAlchemy persistence and Alembic migrations for research records, approvals, and audit events.
- Workflow transitions with human/agent actor conventions and approval rules.
- Literature adapters for OpenAlex, Crossref, Semantic Scholar, and arXiv, with normalization, deduplication, caching, and provenance.
- Anthropic and OpenAI provider interfaces; evidence-linked literature analysis, gap and novelty candidates, and research planning services.
- Dataset version metadata, validation interfaces, experiment specifications, and approval gates.
- Local Python execution with configured allowlists, run lifecycle records, artifact hashes, metrics ingestion, and environment/code provenance.
- Analysis records, scientific claims, and review services.
- A FastAPI and React dashboard for inspection and approval decisions. Creation, generation, and execution remain Python-service operations.

## Architecture

The React dashboard calls the FastAPI adapter, which delegates to the Python domain services. Services use the shared SQLAlchemy repository and database. Evidence services call literature sources; LLM services call configured providers; the execution service launches explicitly allowed local Python modules.

| Directory | Responsibility |
| --- | --- |
| `src/researchos/db`, `workflow` | Persistence, migrations integration, transitions and approvals |
| `src/researchos/evidence`, `llm` | Literature retrieval and provider abstraction |
| `src/researchos/intelligence`, `planning`, `specification` | Reviewable research candidates and experiment specifications |
| `src/researchos/execution`, `analysis` | Runs, provenance, artifacts, metrics, claims and review |
| `apps/dashboard/api`, `apps/dashboard/frontend` | Local inspection dashboard |
| `migrations`, `tests`, `examples` | Schema evolution, regression coverage, runnable examples |

See [architecture](docs/ARCHITECTURE.md), [development](docs/DEVELOPMENT.md), and [roadmap](docs/ROADMAP.md).

## Install from a checkout

Use Python 3.12 or newer. Node.js 24 and npm are needed for the optional dashboard. Keep this source checkout: database migrations and configuration currently resolve relative to it; standalone wheel deployment is not supported.

```sh
git clone https://github.com/burhan19981/ResearchOS.git
cd ResearchOS
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```sh
# macOS / Linux
source .venv/bin/activate
```

From the repository root:

```sh
python -m pip install --upgrade pip
python -m pip install -e ".[dev,dashboard]"
python examples/local_project.py
python -m pytest tests -q
```

The example creates a synthetic project in a temporary SQLite database and removes it on exit. It needs no provider credentials. Tests use mock providers and temporary databases; they do not establish live provider compatibility or research quality.

For a complete local execution tutorial, run `python -m examples.reproducible_experiment`, then `python -m examples.reproducible_experiment --approve-execution`. It demonstrates the approval gate, computes a synthetic regression baseline and fitted-model error, and stores metrics and artifact hashes. See [examples](examples/README.md) and the [first-use guide](docs/TRY_RESEARCHOS.md).

For a persistent local database:

```sh
python -c "from researchos.db import init_db; init_db()"
python -m uvicorn researchos_api.main:app --app-dir apps/dashboard/api --host 127.0.0.1 --port 8000
```

In a second terminal:

```sh
cd apps/dashboard/frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open <http://127.0.0.1:5173>. A new persistent database has no projects. For a populated, explicitly synthetic demonstration, stop the backend and run `npm run e2e:api` from the frontend directory instead. This uses a temporary database. See [examples](examples/README.md).

## Configuration and privacy

Copy `.env.example` to `.env` only if needed, and enter credentials locally. Never commit `.env`, research databases, datasets, logs, or model outputs. Provider calls may send prompt content to external services and incur API charges. Configure an available model explicitly with `ANTHROPIC_MODEL` or `OPENAI_MODEL`; built-in defaults are not a guarantee of availability. Source APIs may require credentials or impose limits; live access has not been verified for this release candidate.

Environment variables are the working configuration interface. `config/settings.example.yaml` only illustrates a future configuration format; no loader currently reads it. Execution is disabled until an operator configures an allowed module prefix. Read [SECURITY.md](SECURITY.md) before enabling it.

## Testing and contribution

```sh
python -m pytest tests -q
cd apps/dashboard/frontend
npm run lint
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

The end-to-end test starts local servers on ports 8000 and 4300; those ports must be free. Browser installation requires network access. See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow and [development guidance](docs/DEVELOPMENT.md) for test scope.

## Known limitations

- No dashboard authentication, per-user permissions, or verified human identity. Actor labels are conventions, not proof of identity.
- Local execution is not containerized or suitable for untrusted code. No implemented Docker, Slurm, cloud, or remote GPU executor.
- No demonstrated end-to-end scientific study, benchmark advantage, user adoption, or real ML training workflow.
- LLM output quality and live provider/source compatibility need separate evaluation; mock tests cannot establish these.
- Dashboard lists are not paginated; no live push updates or in-dashboard generation/creation actions.
- Generic YAML configuration, autonomous orchestration, manuscript generation, and journal submission are not implemented.
- Python dependencies use version ranges rather than a reproducible lockfile; migration assets rely on the source checkout.

Copyright 2026 burhan19981. Licensed under the [Apache License, Version 2.0](LICENSE). Dependency licenses apply separately; see [third-party review](docs/THIRD_PARTY.md).
