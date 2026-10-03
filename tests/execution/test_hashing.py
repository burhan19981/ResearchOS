"""Streaming SHA-256: bounded memory, correct for empty/small/binary/
large files, and independent of chunk size."""

from __future__ import annotations

import hashlib
import os

from researchos.execution.hashing import sha256_file


def test_empty_file_hash_matches_well_known_constant(tmp_path):
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    digest = sha256_file(path)
    assert digest.size_bytes == 0
    assert digest.sha256_hex == hashlib.sha256(b"").hexdigest()
    assert len(digest.sha256_hex) == 64


def test_small_text_file_hash_matches_hashlib_reference(tmp_path):
    path = tmp_path / "small.txt"
    content = b"hello, researchos\n"
    path.write_bytes(content)
    digest = sha256_file(path)
    assert digest.size_bytes == len(content)
    assert digest.sha256_hex == hashlib.sha256(content).hexdigest()


def test_binary_file_hash_matches_hashlib_reference(tmp_path):
    path = tmp_path / "binary.bin"
    content = bytes(range(256)) * 100
    path.write_bytes(content)
    digest = sha256_file(path)
    assert digest.size_bytes == len(content)
    assert digest.sha256_hex == hashlib.sha256(content).hexdigest()


def test_large_file_hash_matches_hashlib_reference_and_uses_small_chunk_size(tmp_path):
    path = tmp_path / "large.bin"
    # ~8 MiB of deterministic pseudo-random-looking content, well above
    # a single small chunk, to prove chunked reading works end-to-end.
    content = os.urandom(8 * 1024 * 1024)
    path.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()

    digest_small_chunks = sha256_file(path, chunk_size=4096)
    digest_default_chunks = sha256_file(path)

    assert digest_small_chunks.sha256_hex == expected
    assert digest_default_chunks.sha256_hex == expected
    assert digest_small_chunks.size_bytes == len(content)
    assert digest_small_chunks.sha256_hex == digest_default_chunks.sha256_hex  # chunk size never affects the result


def test_hash_is_deterministic_across_repeated_calls(tmp_path):
    path = tmp_path / "repeat.bin"
    path.write_bytes(b"deterministic content" * 1000)
    first = sha256_file(path)
    second = sha256_file(path)
    assert first == second
