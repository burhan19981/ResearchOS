> Historical implementation notes. For current setup, status, and security boundaries, see [the README](../README.md) and [SECURITY.md](../SECURITY.md). Historical test counts describe earlier development checkpoints.

# Phase 6: Research Intelligence Layer

Date: 2026-09-17
Scope: LLM-assisted literature analysis, candidate research-gap
generation, and candidate novelty analysis — built on the Phase 5
evidence layer and the Phase 2 provider-agnostic LLM layer, with human
approval integrated through the same `Approval`/`AuditEvent` tables
Phase 4's workflow engine uses. No dashboard, no manuscript generation,
no journal matching, and no autonomous research agents beyond these
three bounded analysis services were built. No real LLM or scholarly
API call was made anywhere in this phase's implementation or test suite.

## Core Principle

**An LLM-generated statement never becomes an authoritative research
fact merely because the LLM produced it.** Five categories are kept
structurally distinct throughout this layer:

1. **Source fact** — a fact directly obtained from an external
   scholarly source (`researchos.evidence`'s domain).
2. **Evidence** — a persisted `LiteratureItem` (source record, DOI,
   abstract, metadata) supporting a statement.
3. **LLM analysis** — an interpretation generated from supplied
   evidence (`LiteratureAnalysis.result`, an `AnalysisClaim`'s text).
4. **Candidate claim** — a hypothesis the system generated that still
   needs human verification (`ClaimApprovalStatus.PENDING_REVIEW`,
   `GapStatus.CANDIDATE`, `NoveltyCandidateStatus.NOT_ASSESSED` and its
   sibling non-terminal values).
5. **Human-approved claim** — explicitly approved by a human
   (`ClaimApprovalStatus.APPROVED`, `GapStatus.VALIDATED`,
   `NoveltyCandidateStatus.HUMAN_APPROVED`).

Nothing in this codebase silently promotes category 3 or 4 into
category 1 or 5. The path is always:

```
LLM output -> candidate -> evidence verification -> human approval -> approved knowledge
```

## Architecture

```
Evidence Layer (researchos.evidence — Phase 5, unmodified)
        │  LiteratureItem rows: source, source_record_id, DOI, abstract, ...
        ▼
Evidence Selection            researchos.intelligence.evidence_package
        │  bounded, deterministic, ranked, explicit truncation
        ▼
LLM Analysis                  researchos.intelligence.llm_call
        │  researchos.llm.get_provider(...).generate_structured(...) — Phase 2, unmodified
        ▼
Structured Analysis Result    researchos.intelligence.{literature_analysis,gap_analysis,novelty_analysis}
        │  schema-validated, then anti-hallucination-checked
        ▼
Candidate Claim / Gap / Novelty Assessment   AnalysisClaim / ResearchGap / NoveltyAssessment
        │
        ▼
Evidence Matrix                researchos.db.models.EvidenceLink
        │  every claim/gap/comparison <-> LiteratureItem relationship, explicit and queryable
        ▼
Human Approval                 researchos.intelligence.approval (reuses Phase 4's Approval table)
        │
        ▼
Approved Research Knowledge    ClaimApprovalStatus.APPROVED / GapStatus.VALIDATED / NoveltyCandidateStatus.HUMAN_APPROVED
```

```
src/researchos/intelligence/
├── __init__.py            # Public API — import from here
├── types.py                 # EvidencePackageItem, EvidencePackage, outcome dataclasses
├── errors.py                  # Normalized exception hierarchy (independent of researchos.llm.errors)
├── prompts.py                   # Versioned prompt templates + JSON schemas (literature_analysis.v1, gap_analysis.v1, novelty_analysis.v1)
├── evidence_package.py             # Deterministic, bounded evidence selection
├── response_validation.py            # The anti-hallucination guard
├── llm_call.py                         # The one place this layer talks to an LLM (via researchos.llm)
├── literature_analysis.py               # Phase 6 spec section 3
├── gap_analysis.py                        # Phase 6 spec section 5
├── novelty_analysis.py                      # Phase 6 spec section 6
└── approval.py                                # Phase 6 spec section 9 — reuses Phase 4's Approval table
```

**What this layer never does**, enforced structurally, not just by
convention:

- Never imports `anthropic`/`openai` directly — only
  `researchos.llm.get_provider(...)`.
- Never imports or modifies `researchos.workflow.service` — workflow
  stage transitions remain that module's exclusive authority.
- Never writes to `LiteratureItem` bibliographic fields (title, DOI,
  authors, abstract, ...) — those remain `researchos.evidence`'s
  exclusive authority. Nothing in `researchos.intelligence` calls
  `repository.update_literature_item()`.
- Never lets an LLM decide a `NoveltyCandidateStatus.HUMAN_APPROVED` or
  `ClaimApprovalStatus`/`GapStatus` approved value — those are only
  ever set by `researchos.intelligence.approval`, which requires a
  human actor.

## Database Changes

One migration
(`migrations/versions/1e460d99a95b_research_intelligence_layer.py`),
built entirely on inspecting the existing Phase 3/5 schema first to
avoid duplication:

**New tables:**

| Table | Purpose |
|---|---|
| `literature_analyses` | One LLM analysis run: requested vs. included evidence ids, truncation flag, provider/model/prompt provenance, structured per-item `result` JSON |
| `analysis_claims` | One traceable claim from a `LiteratureAnalysis`, with `support_level` and `approval_status` |
| `novelty_comparisons` | One row of the candidate-vs-prior-work similarity matrix (Phase 6 spec section 7) |
| `evidence_links` | The unified "Evidence Matrix" (Phase 6 spec section 8) — see below |

**Extended existing tables** (rather than creating parallel ones —
Phase 3 already had `ResearchGap` and `NoveltyAssessment`, which map
almost exactly onto the spec's suggested `GapCandidate` and
`ContributionCandidate`/novelty entities):

- **`research_gaps`**: `gap_type`, `affected_research_area`,
  `evidence_summary`, `prior_work_summary`, `insufficiency_summary`,
  `missing_evidence_summary`, `candidate_research_question`,
  `research_question_id` (FK to `research_questions`, nullable),
  `source_analysis_ids` (JSON), `provider`, `model`, `prompt_name`,
  `prompt_version`. `GapStatus` gained `CHANGES_REQUESTED`.
- **`novelty_assessments`**: `candidate_status` (new
  `NoveltyCandidateStatus` enum — see below), `unresolved_questions`,
  `novelty_risk`, `research_question_id`, `source_gap_ids` (JSON),
  `source_analysis_ids` (JSON), `provider`, `model`, `prompt_name`,
  `prompt_version`. Phase 3's original `status`/`NoveltyStatus` column
  is untouched for backward compatibility; `researchos.intelligence`
  reads/writes `candidate_status` instead. `claim` is reused as-is for
  the "proposed contribution" text — no redundant duplicate column.

All five new enum columns
(`AnalysisStatus`, `ClaimSupportLevel`, `ClaimApprovalStatus`,
`NoveltyCandidateStatus`, `ComparisonStatus`, plus `EvidenceSubjectType`
and `EvidenceRelationship`) use `create_constraint=True` — a real
database `CHECK` constraint — continuing the practice adopted after
Phase 4 discovered Phase 3's original enum columns lacked one, rather
than repeating that gap. Two `research_question_id` foreign keys
needed explicit constraint names
(`fk_research_gaps_research_question_id` /
`fk_novelty_assessments_research_question_id`) for the same reason as
Phase 4's migration: unnamed FK constraints break Alembic's
`downgrade()`. The `novelty_assessments.candidate_status` column also
needed its `CHECK` constraint (`noveltycandidatestatus`) dropped
explicitly before the column itself in `downgrade()`'s batch table
rebuild — the same SQLite-batch-mode nuance discovered in the Phase
4 and Phase 5 migrations.

## Repository Layer

New functions in `researchos.db.repository`, following the existing
explicit-session, no-hidden-commit convention exactly:
`create_literature_analysis`, `get_literature_analysis`,
`list_literature_analyses`, `update_literature_analysis`,
`create_analysis_claim`, `get_analysis_claim`, `list_analysis_claims`,
`update_analysis_claim`, `create_novelty_comparison`,
`list_novelty_comparisons`, `create_evidence_link`,
`list_evidence_links`, `get_approval_by_stage`,
`update_novelty_assessment` (Phase 3 had `record_novelty_assessment`
but no updater). `record_research_gap` and `record_novelty_assessment`
gained the new optional fields listed above. `create_evidence_link`
validates that both the `LiteratureItem` and the polymorphic
`(subject_type, subject_id)` target actually exist in the project
before inserting, since `subject_id` cannot be a real foreign key (it
points into different tables depending on `subject_type`).

## Evidence Package Design

`researchos.intelligence.evidence_package.build_evidence_package()`
turns a list of `LiteratureItem` ids into the narrow
`EvidencePackageItem` projection the Phase 6 spec allows into a
prompt — internal id, source, source_record_id, title, authors, year,
publication_date, venue, DOI, abstract, citation_count, keywords,
provenance (source/source_record_id/retrieved_at/url),
metadata_completeness, evidence_status. Never the raw ORM row, never
`raw_metadata`, never arbitrary fields the spec didn't ask for.

- **Bounded**: `max_items` (default 20) and `max_abstract_chars`
  (default 2000), both caller-overridable.
- **Deterministic ranking on truncation**: `(-metadata_completeness,
  id)` — more-complete evidence first, ties broken by id, so the same
  inputs always select the same subset.
- **Explicit truncation**: `EvidencePackage.truncated` and
  `excluded_item_ids` are always populated; the prompt itself tells the
  model how many items were excluded, and every persisted
  `LiteratureAnalysis`/gap/novelty-assessment row records
  `truncated`/`included_item_ids` so nothing is silently incomplete.
- **Never silently omits a caller's explicit selection**: an unknown or
  cross-project literature_item_id raises `EvidencePackageError`
  immediately rather than being dropped.

## Anti-Hallucination Safeguards (Phase 6 spec sections 13 & 18)

Every service module follows the same pattern after an LLM call
returns:

1. `response_validation.require_object_response()` — defensive shape
   check (never trust that `generate_structured()`'s schema was
   honored strictly; enforcement strictness varies by provider).
2. `response_validation.extract_referenced_ids()` /
   `validate_no_hallucinated_references()` — recursively find every
   integer under any `_id`/`_ids`-suffixed key and compare against the
   evidence package's `included_item_ids`.
3. **Any claim/gap/comparison citing an id outside the package is
   rejected outright** — never partially trusted, never silently
   accepted. Rejected counts are always recorded
   (`rejected_claim_count`, `rejected_candidate_count`,
   `rejected_comparison_count`) and included in the audit event.
4. A claim with **no** cited evidence is coerced to
   `ClaimSupportLevel.UNSUPPORTED_CANDIDATE` regardless of what
   `support_level` the model claimed — the model's own self-assessment
   is never trusted over the actual evidence it cited.
5. **DOIs/authors/titles cannot be injected as bibliographic fact**
   through this layer at all — `AnalysisClaim`, `ResearchGap`, and
   `NoveltyAssessment` have no DOI/author/title columns; those remain
   exclusively `LiteratureItem`'s, owned by `researchos.evidence`. An
   LLM can *mention* a fabricated DOI in claim text, but nothing in
   this layer ever writes it into a bibliographic field.
6. **`NoveltyCandidateStatus.HUMAN_APPROVED` cannot be self-assigned**:
   excluded from the LLM's JSON schema entirely (structural
   prevention), and defensively coerced to `INSUFFICIENT_EVIDENCE` in
   code if it somehow appears anyway (never trust schema enforcement
   alone) — see
   `tests/intelligence/test_novelty_analysis.py::test_llm_cannot_self_assign_human_approved_status`.

## Literature Analysis (Phase 6 spec section 3)

`run_literature_analysis(project_id, research_topic, literature_item_ids, actor=, provider_name=, ...)`.
Builds the evidence package, sends `literature_analysis.v1`'s prompt +
schema through `generate_structured()`, and persists:

- One `LiteratureAnalysis` row: `result` is `{"items": {<id>: {13 dimensions}}, "evidence_item_ids": [...]}`.
  Every dimension a paper's supplied abstract/metadata doesn't address
  is the literal string `"unknown"` — never guessed from the model's
  own training knowledge of the paper.
- Zero or more `AnalysisClaim` rows, each with an `EvidenceLink`
  (relationship `CITES`) per cited literature item.

## Gap Candidate Generation (Phase 6 spec section 5)

`generate_gap_candidates(project_id, research_topic, literature_item_ids, actor=, provider_name=, ...)`.
Every persisted `ResearchGap` starts at `GapStatus.CANDIDATE` — the
system never writes "research gap confirmed." A candidate with zero
`supporting_literature_ids` is rejected outright (an unsupported
assertion is not a usable candidate). `gap_type` remains free text
(methodological/dataset/evaluation/... are examples in the prompt, not
an enforced enum) — exactly like Phase 3's own precedent for
not-yet-formalized vocabularies (`current_stage`,
`ResearchQuestion.type`). Supporting/contradicting evidence becomes
`EvidenceLink` rows (`SUPPORTS`/`CONTRADICTS`), not JSON columns on the
gap itself — see Evidence Matrix below.

## Novelty Candidate Analysis (Phase 6 spec section 6)

`analyze_novelty_candidate(project_id, proposed_contribution, literature_item_ids, actor=, provider_name=, ...)`.
Deliberately not a "novelty detector" — the prompt explicitly forbids a
bare "Novel: Yes" and requires hedged language
("potentially distinct based on the retrieved literature, but
additional verification is required"). Persists one `NoveltyAssessment`
(`claim` = the proposed contribution; only created *after* the LLM
response passes validation — there is no "FAILED" status concept for
this entity, unlike `LiteratureAnalysis`) plus one `NoveltyComparison`
per prior-work item compared against.

## Similarity / Prior Work Matrix (Phase 6 spec section 7)

`NoveltyComparison` **is** the matrix, one row per (candidate,
literature_item_id) pair: `similarity` (text), `difference` (text),
`status` (`ComparisonStatus`: similar / partially_distinct / distinct /
unclear), with its evidence living in `EvidenceLink` rows keyed off the
comparison's own id — `SUPPORTS` = evidence for the similarity claim,
`CONTRADICTS` = evidence for the difference claim. Fully normalized
database rows, not a large unstructured LLM response blob.

## Evidence Matrix (Phase 6 spec section 8)

`EvidenceLink` is the single, unified traceability structure —
deliberately consolidating what would otherwise have been five-plus
scattered JSON-list-of-ids columns (one per relationship type per
entity) into one queryable table:

```python
class EvidenceLink:
    project_id: int
    literature_item_id: int          # -> LiteratureItem (real FK)
    subject_type: EvidenceSubjectType  # ANALYSIS_CLAIM | GAP_CANDIDATE | NOVELTY_ASSESSMENT | NOVELTY_COMPARISON
    subject_id: int                    # polymorphic — validated at the repository layer, not a DB FK
    relationship_type: EvidenceRelationship  # SUPPORTS | CONTRADICTS | RELATED | CITES
```

The full chain from the spec — *Research Question → Claim → Literature
Evidence → Gap → Candidate Contribution → Novelty Assessment* — is
traceable via: `LiteratureAnalysis.research_question_id` /
`ResearchGap.research_question_id` /
`NoveltyAssessment.research_question_id` (all FK to Phase 3's existing
`ResearchQuestion`, reused rather than duplicated),
`AnalysisClaim.analysis_id`, `ResearchGap.source_analysis_ids` /
`NoveltyAssessment.source_analysis_ids`/`source_gap_ids` (JSON lineage
lists), and `EvidenceLink` for every claim/gap/comparison's actual
cited evidence.

## Human Approval Integration (Phase 6 spec section 9)

`researchos.intelligence.approval` reuses Phase 4's `Approval` database
table and `ApprovalDecision` vocabulary directly through
`researchos.db.repository`'s existing primitives
(`create_approval_request`, `record_approval_decision`,
`get_approval_by_stage` — the last one added in this phase, reusable by
`researchos.workflow` too) plus
`researchos.workflow.policy.is_human_actor` for the human-only check —
**no parallel approval mechanism**. `researchos.workflow.service`
itself is neither imported nor modified: its `approve()`/`reject()`
dispatch only understands stage-transition and project-administrative
`Approval.stage` keys, and claims/gaps/novelty-assessments are not
workflow-stage transitions, so this module orchestrates the *same*
underlying table with its own small, consistent decision flow instead
(`CLAIM_APPROVAL:<id>` / `GAP_APPROVAL:<id>` / `NOVELTY_APPROVAL:<id>`
stage-key encoding, directly analogous to how
`researchos.workflow.service` already encodes
`"STAGE_A->STAGE_B"`/`"ARCHIVE_PROJECT"` keys on the same column).

```python
from researchos.intelligence import approval

approval.approve_claim(claim_id, actor="user:pi", comment="well supported")
approval.reject_gap(gap_id, actor="user:pi", comment="too speculative")
approval.request_changes_novelty_assessment(assessment_id, actor="user:pi", comment="need more prior work")
```

- **The LLM cannot approve its own output**: every decision function
  requires `is_human_actor(actor)`; an agent actor raises
  `HumanOnlyActionError` immediately, before any row is touched.
- **Approved-value reuse**: `GapStatus.VALIDATED` (Phase 3's original
  "a human confirmed this" value) is reused for gap approval rather
  than adding a redundant `HUMAN_APPROVED` member; `ClaimApprovalStatus`
  and `NoveltyCandidateStatus` each have their own approved/rejected/
  changes-requested trio for symmetry.
- **Every decision is atomic**: the `Approval` row's decision, the
  candidate's own status field, and an `AuditEvent` all commit in one
  `session_scope()` — the same pattern `researchos.workflow.service`
  uses for its own decisions.
- **A `CHANGES_REQUESTED` decision is not terminal**: a later decision
  on the same candidate opens a fresh pending `Approval` round (mirrors
  a human revising and resubmitting); `APPROVED`/`REJECTED` are
  terminal — a second decision attempt raises
  `ApprovalAlreadyDecidedError`.
- **What's preserved**: who (`AuditEvent.actor`), when
  (`Approval.decided_at`/`AuditEvent.created_at`), what
  (`AuditEvent.metadata_["entity_id"/"entity_type"]`), previous/new
  state (`metadata_["previous_status"/"new_status"]`), and associated
  evidence (`metadata_["evidence_item_ids"]`, gathered from
  `EvidenceLink`).

## LLM Provider Integration (Phase 6 spec section 10)

`researchos.intelligence.llm_call` is the **only** place this layer
talks to an LLM, and it does so exclusively through
`researchos.llm.get_provider(provider_name)` /
`provider.generate_structured(request, schema)` — the exact Phase 2
abstraction, never `anthropic`/`openai` directly. Every analysis
service accepts an optional `provider=` override (mirroring
`researchos.evidence`'s `adapter=` injection pattern) purely for
testing — production code always resolves through the registry.
Temperature is fixed at `0.0` (as deterministic as each provider
supports — Anthropic's current SDK doesn't expose temperature at all;
see `docs/PHASE2_LLM_PROVIDERS.md`'s documented gap, unchanged here) and
`max_tokens` defaults to a bounded `4000`. Retries, timeouts, and
rate-limit handling are already implemented inside each Phase 2
provider — nothing here duplicates that; an `LLMError` that reaches
this layer means the provider's own retries were already exhausted.

## Prompt Versioning (Phase 6 spec section 11)

Every analysis type has a stable, persisted `(prompt_name,
prompt_version)` pair: `literature_analysis.v1`, `gap_analysis.v1`,
`novelty_analysis.v1` (`researchos.intelligence.prompts`). A future
change to a prompt's wording or schema means adding `_v2`, never
silently editing `_v1` in place — so a previously-generated analysis's
provenance always points at the exact prompt text that produced it. No
API key or secret is ever interpolated into a prompt; prompts are built
entirely from static template text, the evidence package's own public
bibliographic fields, and caller-supplied research topics/objectives.

## Cost and Context Control (Phase 6 spec section 12)

Covered by the Evidence Package Design section above: bounded
`max_items`/`max_abstract_chars`, deterministic ranking, and explicit
`truncated`/`included_item_ids`/`excluded_item_ids` tracking — never a
silent omission. `max_tokens=4000` additionally bounds each LLM
response itself.

## Security

- **No API key is ever logged, persisted, or put in a prompt.** Prompts
  are built from templates + evidence + user-supplied text only, none
  of which can carry a credential (verified directly:
  `tests/intelligence/test_llm_provider_integration.py::test_no_secrets_appear_in_prompt_text_or_audit_events`).
  Retry/timeout/rate-limit error messages from the provider layer
  already have secrets redacted at the source
  (`researchos.llm.redaction`, from Phase 2); this layer never
  re-embeds a raw exception's full text into anything user-facing
  beyond `str(exc)` in an audit event, which itself carries no
  credentials because none were ever passed to the LLM call to begin
  with.
- **No provider credential is stored in any database record** — nothing
  in this phase's schema has a column that could hold one; `provider`/
  `model` columns store only a short identifier string
  (`"anthropic"`/`"claude-sonnet-5"`), never a key.
- **No raw Authorization header is exposed** — this layer never
  constructs HTTP requests itself; all of that remains inside
  `researchos.llm`'s existing, already-audited provider implementations.

## Testing

`tests/intelligence/` (67 tests). Every test injects a `FakeLLMProvider`
(`tests/intelligence/fakes.py`, implementing the same shape as
`researchos.llm.base.LLMProvider`) via each service's `provider=`
parameter — **no test in this suite makes, or could make, a real LLM or
scholarly API call.** Fixtures follow the exact pattern established in
`tests/db`/`tests/workflow`/`tests/evidence`: a fresh temporary SQLite
database per test, migrated via the real Alembic path.

| File | Covers |
|---|---|
| `test_evidence_package.py` | Valid package, missing abstract, incomplete metadata, truncation (explicit + deterministic), project isolation |
| `test_literature_analysis.py` | Completed analysis, missing dimensions default to "unknown", truncation reflected on the record, deterministic construction, project isolation, LLM failure marks the row FAILED and re-raises |
| `test_claim_validation.py` | Valid ids, unknown id rejected, no-evidence claim coerced to UNSUPPORTED_CANDIDATE, blank claim rejected, hallucinated analysis-item key dropped, invented DOI never persisted as fact, `response_validation` unit tests |
| `test_gap_analysis.py` | Valid candidate (never auto-confirmed), multiple supporting papers, contradicting evidence, no-support rejection, hallucinated reference rejection, project isolation |
| `test_novelty_analysis.py` | Similarity/difference persisted, similarity vs. difference evidence links kept distinct, insufficient-evidence status, LLM cannot self-assign HUMAN_APPROVED, hallucinated reference rejected (both a bad top-level id and a bad nested evidence id), project isolation |
| `test_approval.py` | Candidates never pre-approved, agents blocked from every decision type, approval/rejection recorded with full audit content, rejection is terminal, changes-requested allows a fresh round, not-found handling |
| `test_llm_provider_integration.py` | Provider abstraction used (no registry touch when injected), bounded/deterministic request shape, malformed response rejected, retryable/non-retryable `LLMError` propagation, no secrets in prompts or audit events |
| `test_reproducibility.py` | prompt_name/prompt_version/provider/model/evidence-ids/timestamp all persisted for every analysis type |

A real integration bug was found and fixed *during* this testing pass
(before any test was written against it) — see Issues Discovered below.

Run with:
```powershell
<repository-root>\.venv\Scripts\python.exe -m pytest tests\intelligence -v
```

## Issues Discovered and Fixed

**Failure-path transaction bug.** The first draft of all three analysis
services wrapped the LLM call, its failure handling (mark `FAILED`,
write an audit event), *and* success-path persistence inside one
`session_scope()` block. Since `session_scope()` rolls back everything
inside it when the exception that triggered a failure-handler is
re-raised, the "mark FAILED + audit event" writes were being silently
undone by the very rollback their own re-raise caused — an analysis
would fail but the row would incorrectly remain stuck at `PENDING`
forever, with no audit trail of the failure. Caught via a manual
end-to-end smoke test before any formal test was written, by comparing
against `researchos.evidence.service`'s already-correct pattern (the
LLM/HTTP call happens *outside* any `session_scope()`; a failure opens
its *own*, separately-committed `session_scope()` for the audit write
before re-raising). All three services were restructured to match; the
fix is directly exercised by
`tests/intelligence/test_literature_analysis.py::test_llm_failure_marks_analysis_failed_and_reraises`.

**Ambiguous SQLAlchemy relationship warnings.** The four new
`ResearchProject.<name>` relationships were initially declared without
`back_populates`, producing `SAWarning`s about overlapping/ambiguous
write targets on the shared `project_id` column (the same class of
issue every other entity in `models.py` already avoids by pairing
`back_populates` on both sides). Fixed by adding `back_populates` in
both directions for all four new relationships.

## Limitations

- **No literature-mapping/dataset/experiment intelligence** — this
  phase covers exactly the three services named in its goals (A, B, C)
  plus the evidence matrix (D) and approval integration (E); it does
  not extend into methodology, dataset, or experiment reasoning.
- **`gap_type` and comparable free-text fields remain unconstrained
  vocabularies** — deliberately, matching Phase 3's own precedent for
  fields without an approved fixed set of values.
- **Evidence ranking is a single deterministic heuristic**
  (metadata completeness, tie-broken by id) — not a relevance-ranking
  model. A future phase could swap this for something smarter without
  changing any calling code.
- **No streaming, no multi-turn refinement** — each analysis call is
  one bounded request/response, matching Phase 2's `generate()`/
  `generate_structured()` contract (no streaming support exists there
  either).
- **Field mappings/prompt effectiveness not verified against a real
  LLM** — per this phase's explicit no-real-API-calls instruction, the
  three prompts have not been validated against Anthropic's or OpenAI's
  actual structured-output behavior; recommend the same kind of
  smoke-test Phase 5.1 performed for the evidence adapters before
  relying on this layer's output quality in production.

## Future Work

- A literature-mapping service that clusters/organizes retrieved
  evidence before analysis (spec's stage 4, "literature mapping" — not
  built here).
- A dashboard surfacing pending intelligence-layer approvals
  (`approval.get_pending_intelligence_approvals()` already returns
  exactly this list; only the presentation layer is missing).
- Extending the workflow engine (Phase 4) to gate specific
  `STAGE_0X_*` transitions on intelligence-layer approvals (e.g.
  requiring at least one `GapStatus.VALIDATED` gap before
  `STAGE_06_NOVELTY_VERIFICATION`) — deliberately not done in this
  phase, which was instructed not to modify the workflow engine.
- A real-LLM smoke test (mirroring Phase 5.1) once the user is ready to
  supply credentials and approve real API calls.
