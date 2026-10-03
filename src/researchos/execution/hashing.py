"""Streaming, bounded-memory file hashing.

Phase 8B-1's artifact recording read an entire file into memory before
hashing it (`orchestrator._maybe_record_artifact` called
`path.read_bytes()`). Phase 8B-2 fixes this: `sha256_file` never holds
more than one chunk of a file in memory at a time, regardless of file
size — correct for a 0-byte file, a small text log, or a large binary
checkpoint alike.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import NamedTuple

_DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MiB


class FileDigest(NamedTuple):
    sha256_hex: str
    size_bytes: int


def sha256_file(path: str | Path, *, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> FileDigest:
    """Compute the sha256 hex digest and exact byte size of the file at
    `path`, reading it in `chunk_size`-byte chunks. Correct for an
    empty file (returns the well-known sha256-of-empty-bytes digest)
    and for arbitrary binary content — never assumes text."""
    hasher = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
            size += len(chunk)
    return FileDigest(sha256_hex=hasher.hexdigest(), size_bytes=size)
