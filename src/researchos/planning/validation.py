"""Post-response validation: the anti-hallucination guard for the
research planning layer.

Every function here runs *after* an LLM call returns and *before*
anything is persisted — the same invariant `researchos.intelligence`
enforces for literature/gap/novelty analysis, reimplemented here (not
imported from there) so this package stays self-contained per its own
package boundary, exactly like every other phase's own small,
independent `errors.py`/validation module. The underlying algorithm is
intentionally identical: any id the model references that was not
explicitly offered to it in its context package is never silently
trusted.
"""

from __future__ import annotations

from typing import Any

from .errors import InvalidPlanningResponseError


def extract_referenced_ids(value: Any) -> set[int]:
    """Recursively collect every integer found under any key whose name
    ends in `_id` or `_ids` (covers research_question_ids,
    literature_item_id, cited_research_question_ids, etc.) without
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
        raise InvalidPlanningResponseError(f"Expected a JSON object, got {type(response).__name__}.")
    missing = [key for key in expected_keys if key not in response]
    if missing:
        raise InvalidPlanningResponseError(f"Response is missing required key(s): {', '.join(missing)}.")
    return response
