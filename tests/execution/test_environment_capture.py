"""Environment capture: never fails a CPU execution just because
`nvidia-smi`/torch/CUDA is unavailable; correctly parses GPU info when
present; never collects secrets or raw environment variables."""

from __future__ import annotations

import subprocess

import pytest

from researchos.execution import environment_snapshot as env_module


def test_collect_environment_info_never_raises_on_a_normal_machine():
    info = env_module.collect_environment_info()
    assert info["python_version"]
    assert info["os_name"]
    assert info["researchos_version"]
    assert isinstance(info["cpu_count"], int) or info["cpu_count"] is None


def test_missing_nvidia_smi_yields_none_not_an_exception(monkeypatch):
    def _raise_not_found(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi not found")

    monkeypatch.setattr(subprocess, "run", _raise_not_found)
    gpu_name, driver_version = env_module._try_nvidia_smi_gpu_info()
    assert gpu_name is None
    assert driver_version is None


def test_nvidia_smi_timeout_yields_none_not_an_exception(monkeypatch):
    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    gpu_name, driver_version = env_module._try_nvidia_smi_gpu_info()
    assert gpu_name is None
    assert driver_version is None


def test_nvidia_smi_nonzero_exit_yields_none(monkeypatch):
    class _FakeCompleted:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted())
    gpu_name, driver_version = env_module._try_nvidia_smi_gpu_info()
    assert gpu_name is None
    assert driver_version is None


def test_nvidia_smi_success_is_parsed_correctly(monkeypatch):
    class _FakeCompleted:
        returncode = 0
        stdout = "NVIDIA GeForce RTX 5060 Laptop GPU, 577.13\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted())
    gpu_name, driver_version = env_module._try_nvidia_smi_gpu_info()
    assert gpu_name == "NVIDIA GeForce RTX 5060 Laptop GPU"
    assert driver_version == "577.13"


def test_gpu_absent_does_not_fail_environment_collection(monkeypatch):
    monkeypatch.setattr(env_module, "_try_nvidia_smi_gpu_info", lambda: (None, None))
    monkeypatch.setattr(env_module, "_try_cuda_info", lambda: (None, None, None))
    info = env_module.collect_environment_info()
    assert info["gpu_name"] is None
    assert info["gpu_driver_version"] is None
    assert info["cuda_version"] is None
    # The rest of the environment is still collected.
    assert info["python_version"]


def test_torch_absent_does_not_fail_environment_collection(monkeypatch):
    def _raise_import_error(name):
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(env_module, "_try_import_version", lambda name: None)
    monkeypatch.setattr(env_module, "_try_cuda_info", lambda: (None, None, None))
    info = env_module.collect_environment_info()
    assert info["pytorch_version"] is None
    assert info["torchvision_version"] is None
    assert "torch" not in info["package_versions"]


def test_environment_info_never_contains_raw_os_environ_dump():
    info = env_module.collect_environment_info()
    assert "environ" not in info
    assert "env" not in info
    serialized = str(info).lower()
    for forbidden in ("api_key", "secret", "password", "token", "credential"):
        assert forbidden not in serialized


def test_cpu_count_always_available_on_this_machine():
    cpu_model, cpu_count = env_module._cpu_info()
    assert cpu_count is not None and cpu_count >= 1


def test_total_memory_bytes_best_effort_never_raises():
    # Should not raise regardless of platform; may legitimately be None.
    value = env_module._try_total_memory_bytes()
    assert value is None or (isinstance(value, int) and value > 0)
