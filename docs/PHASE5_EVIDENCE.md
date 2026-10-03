> Historical implementation notes. For current setup, status, and security boundaries, see [the README](../README.md) and [SECURITY.md](../SECURITY.md). Historical test counts describe earlier development checkpoints.

# Phase 5: Evidence and Literature Layer

Date: 2026-09-17
Scope: A provider-agnostic literature retrieval, normalization,
deduplication, and persistence layer for four scholarly sources
(OpenAlex, Crossref, Semantic Scholar, arXiv), built on top of the
Phase 3 persistence layer. No LLM calls, no research-gap reasoning, no
novelty reasoning, and no dashboard were implemented in this phase, and
no real external network request was made anywhere in its test suite.

## Core Principle

**LLMs are not an authoritative source of bibliographic facts.**
`researchos.evidence` is independent of `researchos.llm` — nothing in
this package imports it, in either direction. A future phase may point
an LLM at evidence already retrieved and persisted here to *analyze*
it, but every title, author, DOI, date, and citation count in this
layer comes from a scholarly API's own response, never from a model.

## Architecture

```
External scholarly sources (OpenAlex, Crossref, Semantic Scholar, arXiv)
        │  HTTP GET (stdlib urllib), timeout + bounded retry + backoff
        ▼
Source Adapters              researchos.evidence.adapters.*
        │  raw JSON/XML -> NormalizedRecord (never fabricates a field)
        ▼
Evidence Normalization       researchos.evidence.normalization
        │  DOI/title canonicalization, completeness scoring
        ▼
Deduplication / Identity Resolution   researchos.evidence.dedup
        │  DOI -> strong external id -> weak title+author+year
        ▼
Evidence Records              researchos.evidence.service._persist_record
        │  upsert-by-(source, source_record_id); duplicates -> new row + LiteratureMatch
        ▼
Persistent Research Database  researchos.db (LiteratureItem, LiteratureMatch)
        │
        ▼
Future LLM analysis  (not built in this phase)
```

```
src/researchos/evidence/
├── __init__.py         # Public API — import from here
├── types.py              # NormalizedRecord, SearchFilters, PageInfo, SearchResult, AdapterHealth
├── errors.py               # Normalized exception hierarchy (independent of researchos.llm.errors)
├── redaction.py              # Secret-masking helpers (duplicated from, not imported from, researchos.llm)
├── config.py                   # Per-source SourceConfig + CacheConfig, all from env vars
├── _http.py                      # UrllibTransport + fetch() — timeout/retry/backoff/rate-limit, stdlib only
├── cache.py                       # Deterministic local cache (FileCache / InMemoryCache / NullCache)
├── normalization.py                 # Pure helpers: DOI/title/author normalization, completeness scoring
├── dedup.py                           # find_duplicate(): DOI -> strong id -> weak title+author+year
├── service.py                           # search_literature() / get_literature_by_id() — the only DB-touching module
└── adapters/
    ├── __init__.py                       # get_adapter() / available_sources() registry
    ├── base.py                             # SourceAdapter ABC + shared HTTP/cache plumbing
    ├── openalex.py, crossref.py, semantic_scholar.py, arxiv.py
```

## Supported Sources

| Source | Base URL (default) | Auth | Notes |
|---|---|---|---|
| OpenAlex | `https://api.openalex.org` | None (optional `mailto` contact) | JSON REST; `ids` bundle used for cross-source dedup |
| Crossref | `https://api.crossref.org` | None (optional `mailto` contact) | JSON REST; primary key *is* the DOI; abstracts rarely present |
| Semantic Scholar | `https://api.semanticscholar.org/graph/v1` | None (optional `x-api-key` header) | JSON REST (Graph API); `externalIds` bundle is a strong dedup signal |
| arXiv | `https://export.arxiv.org/api/query` | None | Atom XML, parsed with stdlib `xml.etree.ElementTree`; every record is a preprint |

All four are public APIs; none requires a secret to function. A
"contact email" is a courtesy identifier some sources' documentation
requests for higher rate limits ("polite pool") — configuring it is
optional and it is never treated as, or handled like, a credential.

## Adapter Interface

Every adapter (`researchos.evidence.adapters.base.SourceAdapter`) implements:

```python
search(query, filters=None, *, page=1, page_size=25, cursor=None) -> SearchResult
get_by_id(source_record_id) -> Optional[NormalizedRecord]   # None means genuinely not found
normalize(raw: dict) -> NormalizedRecord
health() -> AdapterHealth                                    # no network call
```

Adapters share their HTTP/cache/retry wiring through
`SourceAdapter._get_json()` / `_get_text()`, so timeout, retry, and
caching behavior is implemented exactly once — only the URL, query
params, and response shape differ per source. Every adapter accepts
`transport=` and `cache=` constructor overrides, which is how the test
suite replaces the real network with `FakeTransport` (see Testing).

## Normalization

`researchos.evidence.normalization` (pure functions, no I/O):

- **`normalize_doi()`** — strips a known URL/scheme prefix
  (`https://doi.org/`, `doi:`, ...), lowercases, and validates the
  `10.NNNN/suffix` shape. Returns `None` — never a guessed value — for
  anything that doesn't match.
- **`normalize_title()`** — lowercase, punctuation-stripped,
  whitespace-collapsed, for *fuzzy comparison only* — never used to
  assert two records are the same paper.
- **`compute_metadata_completeness()`** — fraction of 8 expected fields
  present (title, authors, year, venue, doi, url, abstract,
  document_type); a `NormalizedRecord` with completeness `< 0.5` gets
  `record_status = PARTIAL_METADATA` instead of `VERIFIED_SOURCE_RECORD`.
- **`reconstruct_openalex_abstract()`** — OpenAlex stores abstracts as a
  word→positions inverted index (a copyright-motivated design on
  OpenAlex's part); this losslessly rebuilds the original word order.
- **`strip_simple_xml_tags()`** — best-effort plain text from an
  occasionally JATS-XML-tagged Crossref abstract.
- **`join_authors()` / `split_authors()`** — the exact, reversible
  convention (`"; "`-joined) used to store a `NormalizedRecord.authors`
  list into `LiteratureItem.authors` (a single `Text` column, a Phase 3
  design choice kept as-is).

**A missing title raises `SourceResponseError`** in every adapter's
`normalize()` — never replaced with a placeholder string. Every other
missing field is simply `None` / empty, with `metadata_completeness`
reflecting exactly how much was supplied.

## Provenance

Every `NormalizedRecord` — and the `LiteratureItem` row it becomes —
preserves:

| Requirement | Field |
|---|---|
| Originating source | `source` |
| Source-specific identifier | `source_record_id` |
| Retrieval timestamp | `retrieved_at` |
| Original URL | `url` |
| Source metadata | `raw_metadata` (the full normalized-from payload, JSON) |

**If multiple sources describe the same paper, both rows survive.**
`_persist_record()` in `service.py` only *updates in place* when the
*exact same* `(source, source_record_id)` is re-fetched (an idempotent
refresh, not a duplicate). A match from a *different* source always
inserts a **new** `LiteratureItem` row — the existing one is never
overwritten or deleted — and records a `LiteratureMatch` explaining the
relationship (see Deduplication). This is the one place provenance
required a small compromise: Phase 3's `UniqueConstraint(project_id, doi)`
would reject a second row with the same DOI, so when a duplicate is
detected by DOI, the *new* row's `doi` column is left `NULL` — the DOI
is not lost (it remains in that row's `raw_metadata` and
`external_ids`, and is stated explicitly in the `LiteratureMatch.notes`
pointing at the canonical row's DOI).

## Deduplication

`researchos.evidence.dedup.find_duplicate()`, in preferred-signal order:

1. **DOI** (normalized) exact match — confidence `1.0`.
2. **Strong external identifier** shared between the candidate and an
   existing record — either record's own `(source, source_record_id)`,
   or an id embedded in either record's `external_ids` (e.g. an
   OpenAlex record's `ids.pmid`, or a Semantic Scholar record's
   `externalIds.ArXiv` matching an arXiv-sourced row) — confidence
   `0.95`.
3. **Normalized title + first-author surname + year** — a *weak*
   fallback, confidence `0.6`, **always** recorded via a
   `LiteratureMatch` row and flagged `RecordStatus.DUPLICATE_CANDIDATE`
   — never silently merged, never deleted, always explainable via
   `LiteratureMatch.notes`.

Two records with merely *similar-looking* titles that don't also share
a matching author surname and year are never linked at all — see
`tests/evidence/test_deduplication.py::test_titles_merely_similar_are_not_treated_as_duplicates_without_author_year_match`.

`LiteratureMatch` (new in this phase) records: `literature_item_id`
(the new/candidate row), `matched_item_id` (the existing/canonical
row), `match_type` (`DOI` / `SOURCE_ID` / `TITLE_AUTHOR_YEAR`),
`confidence`, and `notes` — enough to answer "why were these considered
duplicates?" without needing to re-derive it.

**Scaling note (a known Phase 5 limitation):** `find_duplicate()` scans
every existing `LiteratureItem` in the project — O(n) per new record.
Fine at Phase 5's scale; a future phase should add indexed/precomputed
lookup tables (e.g. a `doi -> item_id` map) if a project's literature
pool grows very large.

## Search

```python
from researchos.evidence import search_literature, SearchFilters

outcome = search_literature(
    project_id, "openalex", "graph neural networks",
    filters=SearchFilters(year_from=2020, author="Jane Doe"),
    actor="agent:lit-bot",
)
outcome.result.records        # this page's NormalizedRecord list
outcome.persisted_items       # the LiteratureItem rows written (or updated)
outcome.matches               # any LiteratureMatch rows created
```

`SearchFilters`: `year_from`, `year_to`, `author`, `venue`, `doi`,
`source`, `document_type`. Each adapter maps these onto its own query
syntax (see each adapter module's docstring) and raises
`UnsupportedFilterError` for a filter it cannot honor — arXiv does this
for `venue`, `doi`, and `document_type`, since none is a meaningful
concept for a preprint server, rather than silently ignoring the filter
and returning unfiltered results.

`get_literature_by_id(project_id, source, source_record_id, actor=...)`
is the single-record equivalent — `outcome.record is None` means a
genuine not-found.

## Pagination

`PageInfo`: `page`, `page_size`, `total` (`None` if the source doesn't
report one — never assume `has_more is False` just because `total` is
unknown), `has_more`, `cursor` (unused by the current four adapters, all
offset/page-based; reserved for a future cursor-paginated source).
`has_more` is computed per-source from whatever pagination metadata that
source actually returns (`meta.count` for OpenAlex, `total-results` for
Crossref, `total`/`next` for Semantic Scholar, `opensearch:totalResults`
for arXiv) — never guessed from the page size alone.

## Rate Limiting / Retries

`researchos.evidence._http.fetch()` (used by every adapter):

- **Timeout**: per-source, configurable (`RESEARCHOS_EVIDENCE_TIMEOUT_SECONDS`, default 20s).
- **Retry**: only on a timeout, HTTP 429, or HTTP 5xx — bounded by
  `RESEARCHOS_EVIDENCE_MAX_RETRIES` (default 3) additional attempts,
  never unbounded.
- **Backoff**: exponential (`0.5 * 2^attempt`, capped at 30s) unless the
  source sends a `Retry-After` header on a 429, which is honored
  exactly (also capped at 30s) — never a busy-loop.
- **Non-retryable 4xx** (400, 401, 403, ...) raises `SourceResponseError`
  immediately — retrying a request that was wrong to begin with only
  wastes the source's rate-limit budget.
- **404** is returned as a plain response (not raised) by `fetch()`
  itself, since it means different things to different callers —
  `get_by_id()` interprets it as "not found" (`None`); `search()`
  callers see a `SourceResponseError` if one somehow occurs.

## Caching

`researchos.evidence.cache` — caches the **raw** response (JSON dict or
XML text), never the normalized record, so a normalization-logic change
can never serve a stale *shape*. Deterministic key:
`sha256(json.dumps({source, operation, sorted(params)}))`, with
`mailto`/`api_key`/`x-api-key`/`key` params excluded from the key
(so the cache never fragments — or leaks anything — based on which
contact identifier or key happens to be configured).

- **`FileCache`** (default) — persists under `data/cache/evidence/`
  (gitignored), so repeated runs across process restarts still avoid
  redundant requests. A corrupted/unreadable cache file is always
  treated as a miss, never an error.
- **`InMemoryCache`** — process-local; used freely in tests.
- **`NullCache`** — always misses; used when `RESEARCHOS_EVIDENCE_CACHE_ENABLED=false`.

Default TTL: 24 hours (`RESEARCHOS_EVIDENCE_CACHE_TTL_SECONDS`) —
bibliographic metadata changes slowly. **Never caches a secret**: no
request header (including the Semantic Scholar API key) is ever part of
a cache key or value; only the source's own public JSON/XML body is
stored.

## Configuration

All from environment variables (optionally via a local `.env`, never
committed) — see `.env.example` for the full annotated list:
`OPENALEX_API_URL`, `OPENALEX_CONTACT_EMAIL`, `CROSSREF_API_URL`,
`CROSSREF_CONTACT_EMAIL`, `SEMANTIC_SCHOLAR_API_URL`,
`SEMANTIC_SCHOLAR_API_KEY`, `ARXIV_API_URL`,
`RESEARCHOS_EVIDENCE_TIMEOUT_SECONDS`, `RESEARCHOS_EVIDENCE_MAX_RETRIES`,
`RESEARCHOS_EVIDENCE_CACHE_ENABLED`, `RESEARCHOS_EVIDENCE_CACHE_DIR`,
`RESEARCHOS_EVIDENCE_CACHE_TTL_SECONDS`. Nothing is hard-coded; every
adapter works with zero configuration (using documented public
defaults) and every optional setting is a plain environment variable,
never a value baked into code.

## Database Changes

One migration (`migrations/versions/<rev>_evidence_layer_literature_extensions.py`):

- **`literature_items`** gains: `source_record_id`, `publisher`,
  `publication_date` (`Date`, populated only when the source gives a
  full day), `document_type`, `citation_count`, `keywords` (JSON),
  `external_ids` (JSON), `raw_metadata` (JSON), `retrieved_at`,
  `record_status` (new enum: `VERIFIED_SOURCE_RECORD` /
  `PARTIAL_METADATA` / `SOURCE_ERROR` / `NOT_FOUND` /
  `DUPLICATE_CANDIDATE` — real `CHECK` constraint, `create_constraint=True`,
  applying the lesson learned in Phase 4), `metadata_completeness`,
  `duplicate_of_id` (self-referential FK, `ON DELETE SET NULL`). A new
  unique constraint `(project_id, source, source_record_id)` supports
  idempotent per-source upserts.
- **`literature_matches`** (new table): `literature_item_id`,
  `matched_item_id` (both FK to `literature_items`, `CASCADE`),
  `match_type` (new enum, `create_constraint=True`), `confidence`,
  `notes`.
- No existing column's type changed and no existing data is touched.

`researchos.db.repository` gained: `get_literature_item_by_doi()`,
`get_literature_item_by_source()`, `update_literature_item()`,
`record_literature_match()`, `list_literature_matches()`, and
`add_literature_item()` accepts the new fields — all following Phase
3's existing explicit-session, no-commit convention.

## Auditability

Every `search_literature()` / `get_literature_by_id()` call writes an
`AuditEvent` — on success, on a genuine not-found, and on a raised
error alike — via `event_type="evidence.search"` /
`"evidence.get_by_id"`. Metadata always includes: `source`, `query` (or
`source_record_id`), `filters`, `page`/`page_size`, `total`, `has_more`,
`result_count`, `persisted_count`, `duplicate_count`, and `error` when
one occurred. **Never** an API key or contact email — those never enter
adapter error message text (verified: `_http.py`'s exception messages
embed only the base URL, never the query-string params), and audit
metadata is built entirely from `SearchFilters`/counts/strings that
never carry credentials in the first place.

## Project Isolation

Every `LiteratureItem` and `LiteratureMatch` row carries `project_id`
(Phase 3's existing FK pattern) — `search_literature()` and
`get_literature_by_id()` always operate within exactly one project, and
`dedup.find_duplicate()` only ever compares a candidate against that
same project's existing records. No global/shared evidence pool was
built in this phase (the spec's "allow shared/global evidence records
only if the architecture supports explicit project associations" — the
architecture does not yet support that, so it was not attempted).

## Testing

`tests/evidence/` (122 tests). Two guarantees from an autouse fixture in
`conftest.py`: `urllib.request.urlopen` is monkeypatched to raise
immediately (so any accidental real request fails loudly, not
silently), and every test gets a fresh temporary SQLite database
migrated via the real Alembic path. `tests/evidence/fakes.py` provides
`FakeTransport` (a queue of canned `HttpResponse`s or exceptions) used
by every adapter/HTTP test — **no test in this suite makes, or could
make, a real network call.**

| File | Covers |
|---|---|
| `test_adapter_interface.py` | Registry, ABC contract, `health()` |
| `test_normalization_openalex.py` / `_crossref.py` / `_semantic_scholar.py` / `_arxiv.py` | Each source's field mapping, missing-title guard, partial-metadata status |
| `test_normalization_helpers.py` | DOI/title normalization, completeness scoring, abstract reconstruction |
| `test_search_and_pagination.py` | Query params, filter translation per adapter, pagination math, `UnsupportedFilterError` |
| `test_deduplication.py` | All three match signals, non-matches, project scoping |
| `test_provenance.py` | Source/id/timestamp/URL/raw_metadata preservation, both-rows-survive, idempotent same-source upsert |
| `test_http_reliability.py` | Timeout retry, `Retry-After` handling, bounded retries, non-retryable 4xx |
| `test_cache.py` | Deterministic keys, secret exclusion, all three cache backends, adapter-level cache hits |
| `test_invalid_and_source_errors.py` | Malformed JSON/XML, arXiv's "200 OK but it's actually an error" quirk, raw `URLError`/timeout translation |
| `test_service.py` | Project isolation, full audit event content, no-secret-leakage |
| `test_offline_guarantee.py` | Proves the network-blocking fixture itself works |

Run with:
```powershell
<repository-root>\.venv\Scripts\python.exe -m pytest tests\evidence -v
```

## Limitations

- **Field mappings were not verified against live APIs.** They were
  implemented from each source's well-established, versioned public
  documentation, but no real network call was made or is permitted in
  this phase (per the Phase 5 instructions) to confirm exact
  field-name accuracy against a live response. Recommend a smoke-test
  against each real API before production use — the same caution
  Phase 2 applied when it discovered the installed LLM SDKs had
  changed shape from what was expected.
- **Deduplication is O(n)** per new record against a project's existing
  literature pool — fine at Phase 5's scale, flagged above for a future
  indexing pass if needed.
- **Crossref abstracts are frequently absent** — a well-known gap in
  Crossref's own data, not this adapter.
- **No literature-mapping/gap/novelty reasoning** — this phase only
  retrieves, normalizes, deduplicates, and persists; it does not decide
  what any of it *means*.
- **No PDF/full-text retrieval** — only metadata, per every source's
  own API scope (none of the four is a full-text service, and Phase 5
  does not bypass any paywall or scrape any website).
- **`RecordStatus.SOURCE_ERROR` / `NOT_FOUND` are not currently
  persisted** to any `LiteratureItem` row (there is nothing concrete to
  store for a failed/absent fetch) — they exist in the shared
  vocabulary for a future phase that may want to log failed lookups
  more richly than an `AuditEvent` alone provides.

## How to Add a New Scholarly Source

1. Create `src/researchos/evidence/adapters/<name>.py` implementing
   `SourceAdapter` (see any existing adapter as a template) — it should
   be the only module that knows that source's URL/response shape.
2. Add a `load_<name>_config()` function to `config.py` following the
   existing `SourceConfig` shape and the `<NAME>_API_URL` / optional
   `<NAME>_CONTACT_EMAIL` / `<NAME>_API_KEY` naming convention.
3. Register the class in `adapters/__init__.py`'s `_REGISTRY`.
4. Add the new env vars to `.env.example` (names/comments only).
5. Add normalization + search/pagination/error tests mirroring the
   existing adapter's test files, using `FakeTransport` — no real
   network calls.

No changes are needed anywhere else — `search_literature()` and
`get_literature_by_id()` already work with any registered adapter name.
