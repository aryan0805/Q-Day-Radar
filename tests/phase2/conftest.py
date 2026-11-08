"""Phase 2 safety net. Owned by reviewer.

Nothing under tests/phase2 may reach IBM: no network, no token, no real QiskitRuntimeService,
and the real ledger (results/budget.json) and results/hardware must be byte-identical after
every test. A test that breaks one of these fails loudly instead of spending QPU seconds.
"""

from __future__ import annotations

import socket

import pytest

from tests.phase2.guards import ROOT, TOKEN_VARS, NetworkAccessError, tree_digest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise NetworkAccessError(f"network access attempted in a phase-2 test: {args[:2]}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture(autouse=True)
def _no_token_no_saved_account(monkeypatch, tmp_path):
    for var in TOKEN_VARS:
        monkeypatch.delenv(var, raising=False)
    # a saved account lives in ~/.qiskit/qiskit-ibm.json; point HOME at an empty directory
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))


@pytest.fixture(autouse=True)
def _no_real_service(monkeypatch):
    """A real QiskitRuntimeService cannot be built in a test; tests inject fakes instead."""
    try:
        import qiskit_ibm_runtime
    except ImportError:  # pragma: no cover
        return

    def refuse(*args, **kwargs):
        raise AssertionError("a phase-2 test tried to construct a real QiskitRuntimeService")

    monkeypatch.setattr(qiskit_ibm_runtime.QiskitRuntimeService, "__init__", refuse)


@pytest.fixture(autouse=True)
def _real_ledger_and_hardware_untouched():
    watched = (ROOT / "results" / "budget.json", ROOT / "results" / "hardware")
    before = tree_digest(*watched)
    yield
    after = tree_digest(*watched)
    assert after == before, "a phase-2 test modified results/budget.json or results/hardware"
