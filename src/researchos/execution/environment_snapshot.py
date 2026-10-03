"""Deterministic, offline collection of the environment a `Run` actually
executes in, plus its canonical hash.

Never assumes CUDA/a GPU exists — ResearchOS must work on CPU-only
machines. Never collects environment *variables* (secrets
could live there) — only library/interpreter/OS version facts and
installed-package versions, which is a fundamentally different, much
narrower surface than `os.environ`.

Reuses `researchos.specification.fingerprint`'s canonicalization/hash
convention directly (`canonicalize` + `sha256_hex`) rather than a
second hashing scheme — the same sorted-keys, no-incidental-whitespace
JSON serialization, so two collections of the same facts always hash
identically regardless of dict ordering.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from typing import Any, Optional

from sqlalchemy.orm import Session

from .. import __version__ as researchos_version
from ..db import repository
from ..db.models import EnvironmentSnapshot
from ..specification.fingerprint import canonicalize, sha256_hex


def _try_import_version(module_name: str) -> Optional[str]:
    try:
        module = __import__(module_name)
    except ImportError:
        return None
    return getattr(module, "__version__", None)


def _try_cuda_info() -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Returns (cuda_version, cudnn_version, gpu_name) — all `None` on
    any CPU-only machine or if torch is not installed. Uses only
    torch's own Python API; never assumes availability."""
    try:
        import torch  # noqa: PLC0415
    except ImportError:
        return None, None, None
    if not torch.cuda.is_available():
        return None, None, None
    cuda_version = getattr(torch.version, "cuda", None)
    try:
        cudnn_raw = torch.backends.cudnn.version()
        cudnn_version = str(cudnn_raw) if cudnn_raw is not None else None
    except Exception:
        cudnn_version = None
    try:
        gpu_name = torch.cuda.get_device_name(0)
    except Exception:
        gpu_name = None
    return cuda_version, cudnn_version, gpu_name


def _try_nvidia_smi_gpu_info() -> tuple[Optional[str], Optional[str]]:
    """Best-effort `(gpu_name, gpu_driver_version)` via one fixed,
    hardcoded `nvidia-smi` invocation — never shell, never any
    caller-influenced argv, exactly like
    `researchos.execution.git_provenance`'s fixed `git` argv. Returns
    `(None, None)` on any failure (not installed, no GPU, timeout,
    unexpected output) rather than raising — a missing `nvidia-smi`
    must never fail a CPU execution (Phase 8B-2 spec section 16/17).
    Queried independent of whether the installed PyTorch build can
    actually use CUDA (so "a GPU is physically present" and "this
    run's PyTorch can use CUDA" are deliberately kept as distinguishable
    facts)."""
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None, None
    if completed.returncode != 0:
        return None, None
    first_line = completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""
    parts = [part.strip() for part in first_line.split(",")]
    if len(parts) != 2:
        return None, None
    name, driver_version = parts
    return (name or None), (driver_version or None)


def _cpu_info() -> tuple[Optional[str], Optional[int]]:
    """`(cpu_model, cpu_count)` — `cpu_count` is always reliable
    (`os.cpu_count()`); `cpu_model` is best-effort (`platform.
    processor()` returns an empty string on many Linux distributions,
    a real model string on Windows)."""
    return (platform.processor() or None), os.cpu_count()


def _try_total_memory_bytes() -> Optional[int]:
    """Best-effort total physical RAM in bytes. No new dependency is
    introduced for this (no `psutil`): Windows uses `ctypes` +
    `GlobalMemoryStatusEx`, Linux parses `/proc/meminfo`. Returns
    `None` on any failure or on a platform this function does not
    special-case (e.g. macOS) — never raises, matching every other
    best-effort environment fact in this module."""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return int(status.ullTotalPhys)
            return None
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("MemTotal:"):
                        kilobytes = int(line.split()[1])
                        return kilobytes * 1024
            return None
        return None
    except Exception:
        return None


def collect_environment_info() -> dict[str, Any]:
    """Collect the facts one `EnvironmentSnapshot` records, purely from
    already-running-interpreter introspection plus (best-effort, never
    required) `nvidia-smi`. Deterministic for a fixed machine/environment
    — no timestamps, no temporary paths, no environment variables."""
    cuda_version, cudnn_version, torch_gpu_name = _try_cuda_info()
    gpu_name, gpu_driver_version = _try_nvidia_smi_gpu_info()
    if gpu_name is None:
        gpu_name = torch_gpu_name
    cpu_model, cpu_count = _cpu_info()
    package_versions = {
        name: version
        for name, version in (
            ("torch", _try_import_version("torch")),
            ("torchvision", _try_import_version("torchvision")),
            ("numpy", _try_import_version("numpy")),
            ("sqlalchemy", _try_import_version("sqlalchemy")),
        )
        if version is not None
    }
    return {
        "os_name": platform.system() or None,
        "os_version": platform.release() or None,
        "architecture": platform.machine() or None,
        "python_version": platform.python_version(),
        "pytorch_version": package_versions.get("torch"),
        "torchvision_version": package_versions.get("torchvision"),
        "cuda_version": cuda_version,
        "cudnn_version": cudnn_version,
        "gpu_name": gpu_name,
        "gpu_driver_version": gpu_driver_version,
        "package_versions": package_versions,
        "cpu_model": cpu_model,
        "cpu_count": cpu_count,
        "total_memory_bytes": _try_total_memory_bytes(),
        "researchos_version": researchos_version,
    }


def compute_environment_hash(info: dict[str, Any]) -> str:
    return sha256_hex(canonicalize(info))


def record_environment(session: Session, info: Optional[dict[str, Any]] = None) -> EnvironmentSnapshot:
    """Create-or-get: collect (or accept a caller-supplied, e.g.
    test-injected) environment `info`, and return the existing
    `EnvironmentSnapshot` row for its hash if one already exists rather
    than inserting a duplicate — `EnvironmentSnapshot` is
    content-addressable (see its docstring in `researchos.db.models`)."""
    collected = info if info is not None else collect_environment_info()
    environment_hash = compute_environment_hash(collected)
    existing = repository.get_environment_snapshot_by_hash(session, environment_hash)
    if existing is not None:
        return existing
    return repository.create_environment_snapshot(session, environment_hash=environment_hash, **collected)
