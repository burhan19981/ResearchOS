"""Test #22: offline/fixture-based testing — proves the safety net itself
works, rather than only assuming it does.
"""

from __future__ import annotations

import urllib.request

import pytest

from researchos.evidence._http import UrllibTransport
from researchos.evidence.adapters import available_sources, get_adapter


def test_real_network_call_is_blocked_by_the_autouse_fixture():
    """`block_real_network_calls` (conftest.py) must make any real
    `urlopen` call fail loudly rather than silently reach the network."""
    with pytest.raises(AssertionError, match="real network call"):
        urllib.request.urlopen("https://example.com", timeout=1)


def test_real_transport_get_is_also_blocked():
    transport = UrllibTransport()
    with pytest.raises(AssertionError, match="real network call"):
        transport.get("https://example.com", timeout=1.0)


def test_every_adapter_can_be_constructed_and_health_checked_fully_offline():
    """Constructing an adapter and checking its health must never touch
    the network — both should work even with the block in place."""
    for name in available_sources():
        adapter = get_adapter(name)
        health = adapter.health()
        assert health.source == name
