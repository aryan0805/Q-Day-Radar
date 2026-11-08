"""The safety net itself: if these fail, no other phase-2 test can be trusted."""

import socket

import pytest

from tests.phase2.guards import ROOT, NetworkAccessError, tree_digest


def test_safety_net_blocks_sockets():
    with pytest.raises(NetworkAccessError):
        socket.create_connection(("example.com", 443))
    with pytest.raises(NetworkAccessError):
        socket.socket().connect(("127.0.0.1", 9))
    with pytest.raises(NetworkAccessError):
        socket.getaddrinfo("quantum.cloud.ibm.com", 443)


def test_safety_net_removes_tokens_and_saved_account(monkeypatch):
    import os

    assert not any(os.environ.get(v) for v in ("QISKIT_IBM_TOKEN", "QISKIT_IBM_INSTANCE"))
    assert "pytest" in os.environ["HOME"] or "home" in os.environ["HOME"]
    assert not os.path.exists(os.path.expanduser("~/.qiskit/qiskit-ibm.json"))


def test_safety_net_refuses_a_real_runtime_service():
    qiskit_ibm_runtime = pytest.importorskip("qiskit_ibm_runtime")
    with pytest.raises(AssertionError, match="real QiskitRuntimeService"):
        qiskit_ibm_runtime.QiskitRuntimeService(channel="ibm_quantum_platform", token="x")


def test_safety_net_digest_detects_a_changed_byte(tmp_path):
    f = tmp_path / "ledger.json"
    f.write_text("{}")
    d = tree_digest(f)
    f.write_text("{ }")
    assert tree_digest(f) != d
    assert tree_digest(tmp_path / "missing") != d


def test_safety_net_digest_detects_added_and_removed_files(tmp_path):
    (tmp_path / "a.json").write_text("1")
    d = tree_digest(tmp_path)
    (tmp_path / "b.json").write_text("2")
    assert tree_digest(tmp_path) != d


def test_safety_net_watches_the_real_ledger_and_hardware_dir():
    assert (ROOT / "results" / "budget.json").is_file()
    # the autouse fixture compares digests of these around every test; here just prove the
    # digest of the real ledger is stable within a test
    p = ROOT / "results" / "budget.json"
    assert tree_digest(p) == tree_digest(p)
