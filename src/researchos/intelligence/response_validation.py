"""Post-response validation: the anti-hallucination guard.

Every function here runs *after* an LLM call returns and *before*
anything is persisted. This is where the Phase 6 spec section 13
invariant is enforced: a literature_item_id the model references but
that was not in the evidence package it was given is never silently
accepted — the offending item is rejected here, not trusted.
"""

from __future__ import annotations

from typing import Any

from .errors import InvalidAnalysisResponseError


def extract_referenced_ids(value: Any) -> set[int]:
    """Recursively collect every integer found under any key whose name
    ends in `_id` or `_ids` (covers evidence_item_ids, literature_item_id,
    supporting_literature_ids, similarity_evidence_ids, etc.) without
    hard-coding every field name individually."""
    found: set[int] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key.endswith("_id") or key.endswith("_ids"):
                    if isinstance(val, int):
                        found.add(val)
                    elif isinstance(val, list):
                        found.update(v for v in val if isinstance(v, int))
                _walk(val)
        elif isinstance(node, list):
            for entry in node:
                _walk(entry)

    _walk(value)
    return found


def validate_no_hallucinated_references(response: dict[str, Any], allowed_item_ids: set[int]) -> set[int]:
    """Return the set of referenced ids NOT present in `allowed_item_ids`.

    An empty return value means the response is clean. Callers use this
    to reject/mark-invalid specific claims/gaps/comparisons that cite an
    id outside the evidence package — see each service module for exactly
    how a violation is handled (the response is never "silently accepted").
    """
    referenced = extract_referenced_ids(response)
    return referenced - allowed_item_ids


def require_object_response(response: Any, *, expected_keys: tuple[str, ...]) -> dict[str, Any]:
    """Defensive shape check before touching a raw LLM JSON response.

    `generate_structured()` already returns a parsed dict (Phase 2's
    contract), but a provider could still return a technically-valid
    JSON value of the wrong shape (e.g. a bare list, or missing the keys
    this analysis type requires) — checked here rather than trusting the
    schema was honored strictly, since enforcement strictness varies by
    provider/version.
    """
    if not isinstance(response, dict):
        raise InvalidAnalysisResponseError(f"Expected a JSON object, got {type(response).__name__}.")
    missing = [key for key in expected_keys if key not in response]
    if missing:
        raise InvalidAnalysisResponseError(f"Response is missing required key(s): {', '.join(missing)}.")
    return response
