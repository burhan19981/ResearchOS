"""Post-response validation: the anti-hallucination guard for the
analysis & scientific review layer.

Reimplemented here (not imported from `researchos.planning` or
`researchos.intelligence`) per this codebase's package-independence
convention — every phase gets its own small copy of this exact
algorithm. Any id an LLM references that was not explicitly offered to
it in its context package is never silently trusted (Phase 8 spec
section 20).
"""

from __future__ import annotations

from typing import Any

from .errors import InvalidAnalysisResponseError


def extract_referenced_ids(value: Any) -> set[int]:
    """Recursively collect every integer found under any key whose name
    ends in `_id` or `_ids` (covers analysis_record_id,
    supporting_analysis_record_ids, etc.) without hard-coding every
    field name individually."""
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


def validate_no_hallucinated_references(response: dict[str, Any], allowed_ids: set[int]) -> set[int]:
    """Return the set of referenced ids NOT present in `allowed_ids`.

    An empty return value means the response is clean. Callers use this
    to reject/drop specific generated entries that cite an id outside
    what they were given — never partially trusted, never silently
    accepted.
    """
    referenced = extract_referenced_ids(response)
    return referenced - allowed_ids


def require_object_response(response: Any, *, expected_keys: tuple[str, ...]) -> dict[str, Any]:
    """Defensive shape check before touching a raw LLM JSON response.

    `generate_structured()` already returns a parsed dict (Phase 2's
    contract), but a provider could still return a technically-valid
    JSON value of the wrong shape — checked here rather than trusting
    the schema was honored strictly, since enforcement strictness varies
    by provider/version.
    """
    if not isinstance(response, dict):
        raise InvalidAnalysisResponseError(f"Expected a JSON object, got {type(response).__name__}.")
    missing = [key for key in expected_keys if key not in response]
    if missing:
        raise InvalidAnalysisResponseError(f"Response is missing required key(s): {', '.join(missing)}.")
    return response
