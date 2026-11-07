"""Phase 0 starter test: the toolchain is the one the plan assumes.

Reviewer adds the Bell-state, FakeKingston and budget-guard tests from the
Phase 0 brief in this folder.
"""

import qiskit
import qiskit_aer
import qiskit_ibm_runtime


def test_qiskit_is_v2():
    assert qiskit.__version__.startswith("2.")


def test_runtime_has_v2_sampler_and_heron_fake_backend():
    from qiskit_ibm_runtime import SamplerV2  # noqa: F401
    from qiskit_ibm_runtime.fake_provider import FakeKingston

    backend = FakeKingston()
    assert backend.num_qubits >= 100


def test_aer_imports():
    assert qiskit_aer.AerSimulator is not None
    assert qiskit_ibm_runtime.__version__
