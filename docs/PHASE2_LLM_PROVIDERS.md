> Historical implementation notes. For current setup, status, and security boundaries, see [the README](../README.md) and [SECURITY.md](../SECURITY.md). Historical test counts describe earlier development checkpoints.

# Phase 2: LLM Provider Layer

Date: 2026-09-17
Scope: A provider-agnostic LLM integration layer supporting Anthropic and
OpenAI. No agents, workflows, database logic, or dashboard were built.
No real API calls were made during this phase.

## Architecture

```
src/researchos/llm/
├── __init__.py            # Public API surface — import from here only
├── types.py                # Message, GenerationRequest, GenerationResult, Usage
├── errors.py                # Normalized exception hierarchy
├── redaction.py             # Secret-masking helpers
├── base.py                  # LLMProvider abstract base class
├── config.py                 # Env-var configuration loading (+ .env support)
├── retry.py                  # Dependency-free retry-with-backoff helper
├── _sdk_error_mapping.py     # Shared SDK-exception → normalized-error mapping
├── anthropic_provider.py     # AnthropicProvider — only module importing `anthropic`
├── openai_provider.py        # OpenAIProvider — only module importing `openai`
└── registry.py                # get_provider() / get_provider_status() factory
```

The core design goal: **application and agent code never imports
`anthropic` or `openai` directly.** Everything goes through
`researchos.llm`:

```python
from researchos.llm import get_provider, GenerationRequest, Message

provider = get_provider("anthropic")  # or "openai"
if provider.is_configured():
    result = provider.generate(
        GenerationRequest(messages=[Message(role="user", content="Hello")])
    )
```

If a third provider is added later, only a new `*_provider.py` module and
a registry entry are needed — no call site elsewhere in the codebase
changes.

## Provider Abstraction (`base.LLMProvider`)

An abstract base class defining the contract every provider must
satisfy:

| Member | Purpose |
|---|---|
| `provider_name` | Stable identifier, e.g. `"anthropic"` |
| `model_name` | The model this instance is configured to use |
| `is_configured()` (classmethod) | Whether credentials are present — never exposes them |
| `generate(request)` | Text completion |
| `generate_structured(request, schema)` | JSON-schema-conformant completion; default raises `LLMUnsupportedOperationError`, overridden where the provider supports it natively |

`GenerationRequest` carries `messages`, optional `temperature`,
`max_tokens`, `timeout`, and an `extra` dict reserved for
provider-specific passthrough in a future phase. `GenerationResult`
carries `text`, `provider`, `model`, `finish_reason`, and `usage`
(`input_tokens` / `output_tokens` / `total_tokens`, where available).

## Supported Providers

### Anthropic (`anthropic_provider.AnthropicProvider`)

- Uses `anthropic.Anthropic().messages.create(...)`.
- Splits `system`-role messages out of the conversation into the
  top-level `system` parameter, as the Anthropic API expects.
- Implements `generate_structured()` natively via
  `output_config={"format": {"type": "json_schema", "schema": ...}}`,
  which the installed SDK (`anthropic` 1.6.0) supports directly.
- **Known limitation:** the installed SDK's `messages.create()` no
  longer exposes a top-level `temperature` parameter — newer Claude
  model families are tuned via `output_config.effort` instead, which
  this phase does not implement (not requested, and not safely
  guessable without real credentials to verify against). If a caller
  sets `GenerationRequest.temperature` for this provider, a
  `RuntimeWarning` is emitted and the request proceeds without it,
  rather than silently dropping it or guessing at an undocumented
  mapping. This should be revisited in a future phase once real
  credentials are available to confirm current API behavior.

### OpenAI (`openai_provider.OpenAIProvider`)

- Uses `openai.OpenAI().chat.completions.create(...)`.
- `temperature` is passed through directly — still a native top-level
  parameter in the installed SDK (`openai` 3.14.1).
- Implements `generate_structured()` natively via
  `response_format={"type": "json_schema", "json_schema": {...}}`.

Both providers construct their SDK client **lazily** — a provider
object can always be created (e.g. by the registry) without triggering
any network call or requiring credentials; the client is only built,
and credentials only checked, on the first call to `generate()` /
`generate_structured()`.

## Configuration (`config.py`)

Configuration is read from environment variables, optionally populated
from a local `.env` file via `python-dotenv` (`load_dotenv(..., override=False)`
— real process environment variables always win over `.env` contents).

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic credential | *(none — required to use the provider)* |
| `ANTHROPIC_MODEL` | Model name | `claude-sonnet-5` |
| `ANTHROPIC_TIMEOUT_SECONDS` | Request timeout | `60` |
| `ANTHROPIC_MAX_RETRIES` | Retry attempts on transient errors | `2` |
| `OPENAI_API_KEY` | OpenAI credential | *(none — required to use the provider)* |
| `OPENAI_MODEL` | Model name | `gpt-4o-mini` |
| `OPENAI_TIMEOUT_SECONDS` | Request timeout | `60` |
| `OPENAI_MAX_RETRIES` | Retry attempts on transient errors | `2` |

**On the default models:** these are documented, overridable starting
points, not guarantees of current availability, pricing, or
suitability. `claude-sonnet-5` and `gpt-4o-mini` were chosen as
reasonably capable, cost-conscious defaults available at the time of
writing; verify against your own provider account before relying on
them, and override via `ANTHROPIC_MODEL` / `OPENAI_MODEL` at any time.

An invalid non-numeric value for a timeout/retry env var falls back to
the documented default rather than raising, since a malformed
configuration value should not itself crash the process before any LLM
call is attempted.

## Provider Factory / Registry (`registry.py`)

```python
from researchos.llm import get_provider, get_provider_status, available_providers

available_providers()      # -> ["anthropic", "openai"]
get_provider("openai")      # -> OpenAIProvider instance (safe: no network call)
get_provider("does-not-exist")  # -> raises LLMConfigurationError
get_provider_status()       # -> {"anthropic": False, "openai": False} (booleans only)
```

`get_provider()` is case-insensitive and strips surrounding whitespace.
An unknown name raises `LLMConfigurationError` rather than a bare
`KeyError`/`ValueError`, keeping all caller-facing failures within the
normalized error hierarchy.

## How to Add Another Provider Later

1. Create `src/researchos/llm/<name>_provider.py` implementing
   `LLMProvider` (see `anthropic_provider.py` / `openai_provider.py` as
   templates). It should be the *only* module importing that
   provider's SDK.
2. Add a `load_<name>_config()` function to `config.py` following the
   existing `ProviderConfig` shape and env-var naming convention
   (`<NAME>_API_KEY`, `<NAME>_MODEL`, etc.).
3. Register the class in `registry._REGISTRY`.
4. Add the new env vars to `.env.example` (names/comments only).
5. Add provider-specific tests mirroring the existing test files, using
   fakes/mocks — no real credentials or network calls.

No changes are needed anywhere else — callers already depend only on
`get_provider()`.

## Security Considerations

- **No hard-coded secrets anywhere in the codebase.** Credentials are
  read exclusively from environment variables / a local `.env` file.
- **`.env` is gitignored** (see root `.gitignore`); only `.env.example`
  (names and comments, no values) is tracked.
- **No secret is ever logged or included in an exception message.**
  `redaction.redact_secret()` masks a value for safe display (e.g. a
  future CLI/status command); `redaction.strip_secret_from_text()`
  scrubs an exact secret value out of raw SDK error text before it is
  wrapped into a normalized `LLMError`.
- **Configuration presence, not the value, is exposed.** `is_configured()`
  and `get_provider_status()` return booleans only.
- **No real API calls were made during this phase**, in line with the
  Phase 2 instructions. All provider tests mock the SDK client.

## Error Normalization

All provider-raised errors are subclasses of `LLMError`
(`src/researchos/llm/errors.py`):

| Normalized error | Meaning |
|---|---|
| `LLMConfigurationError` | Missing credentials, or an unknown provider name |
| `LLMAuthenticationError` | Provider rejected the credentials |
| `LLMTimeoutError` | Request exceeded its timeout |
| `LLMRateLimitError` | Provider reported rate limiting |
| `LLMProviderUnavailableError` | Connection failure, 5xx, or any unrecognized SDK error (safe fallback bucket) |
| `LLMMalformedResponseError` | Response could not be parsed into the expected shape |
| `LLMUnsupportedOperationError` | Operation not implemented by this provider (e.g. `generate_structured` on a provider without an override) |

`_sdk_error_mapping.normalize_sdk_exception()` maps by **exception
class name** across the raised exception's MRO, rather than importing
both SDKs' exception hierarchies everywhere. This keeps SDK imports
confined to their own provider module and made the mapping logic
straightforward to unit test with lightweight fake exception classes
(see `tests/llm/test_sdk_error_mapping.py`).

`retry.call_with_retries()` retries only the three transient error
types (`LLMTimeoutError`, `LLMRateLimitError`,
`LLMProviderUnavailableError`) with linear backoff, up to each
provider's configured `max_retries`. Configuration and authentication
errors are never retried.

## Testing Approach

- **No real credentials or network calls anywhere in the test suite.**
  Every provider-level test replaces `_get_client()` with a fake object
  via `monkeypatch`.
- **Environment isolation:** an autouse fixture
  (`tests/llm/conftest.py::clean_llm_env`) clears all LLM-related env
  vars before every test, and a second autouse fixture disables
  `.env` file loading, so results never depend on a developer's local
  `.env` or shell environment.
- **SDK-agnostic exception mapping tests** use small fake exception
  classes named after real SDK exceptions (e.g. a local
  `class RateLimitError(Exception)`) rather than constructing real
  `anthropic`/`openai` exception instances, several of which require
  internal SDK objects (like an `httpx` request) to construct.
- Run the suite with:
  ```powershell
  <repository-root>\.venv\Scripts\python.exe -m pytest tests\ -v
  ```

Test files:

| File | Covers |
|---|---|
| `test_config.py` | Env var loading, defaults, invalid values, blank-string handling |
| `test_registry.py` | Factory behavior, unknown provider names, status reporting |
| `test_errors_and_redaction.py` | Error hierarchy shape, secret masking |
| `test_sdk_error_mapping.py` | SDK exception → normalized error translation |
| `test_retry.py` | Backoff, give-up behavior, non-retryable errors |
| `test_anthropic_provider.py` | `generate`/`generate_structured`, error paths, temperature warning |
| `test_openai_provider.py` | `generate`/`generate_structured`, error paths, temperature passthrough |

## What Is Intentionally NOT Implemented Yet

- No agents, tools, or orchestration logic.
- No workflows or multi-step chains.
- No database persistence for conversations, usage, or results.
- No dashboard/UI.
- No literature search or any research-domain functionality.
- No streaming responses (`generate()` is request/response only).
- No prompt-caching, tool-use/function-calling, or multi-turn session
  management beyond what `GenerationRequest.messages` already allows
  the caller to construct.
- No `effort`-level control for Anthropic (see the temperature
  limitation above) or `reasoning_effort` control for OpenAI.
- No live verification against real provider accounts — SDK behavior
  here was confirmed by introspecting the installed packages'
  signatures and type definitions, not by making real requests. This
  should be validated with real credentials before production use.
- Docker and Node.js remain uninstalled, per Phase 2 constraints.
