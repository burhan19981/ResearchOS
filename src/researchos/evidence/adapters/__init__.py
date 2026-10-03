"""Adapter registry: obtain a `SourceAdapter` by name without knowing
which module/class implements it.

```python
from researchos.evidence.adapters import get_adapter, available_sources

available_sources()   # -> ["arxiv", "crossref", "openalex", "semantic_scholar"]
get_adapter("openalex")  # -> OpenAlexAdapter instance (safe: no network call)
```

Adding a fifth source later means adding one module here implementing
`SourceAdapter` and one line in `_REGISTRY` — nothing else in
`researchos.evidence` needs to change. See
`docs/PHASE5_EVIDENCE.md#how-to-add-a-new-scholarly-source`.
"""

from __future__ import annotations

from typing import Callable, Dict, List

from ..errors import SourceConfigurationError
from .arxiv import ArxivAdapter
from .base import SourceAdapter
from .crossref import CrossrefAdapter
from .openalex import OpenAlexAdapter
from .semantic_scholar import SemanticScholarAdapter

_REGISTRY: Dict[str, Callable[..., SourceAdapter]] = {
    "openalex": OpenAlexAdapter,
    "crossref": CrossrefAdapter,
    "semantic_scholar": SemanticScholarAdapter,
    "arxiv": ArxivAdapter,
}


def available_sources() -> List[str]:
    return sorted(_REGISTRY)


def get_adapter(name: str, **kwargs) -> SourceAdapter:
    """Instantiate an adapter by name. Never makes a network call."""
    key = (name or "").strip().lower()
    if key not in _REGISTRY:
        raise SourceConfigurationError(
            f"Unknown evidence source '{name}'. Available sources: {', '.join(available_sources())}."
        )
    return _REGISTRY[key](**kwargs)


__all__ = ["SourceAdapter", "get_adapter", "available_sources"]
