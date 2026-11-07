"""Backend factory: ideal simulator, noisy FakeKingston simulator, real IBM backend.

Nothing here submits a job. Hardware submission lives in ``quantum/run/hardware.py``
and must be approved by ``quantum/run/budget.py`` first.
"""

from __future__ import annotations

import os
from typing import Literal

from qiskit.providers import BackendV2
from qiskit_aer import AerSimulator
from qiskit_ibm_runtime.fake_provider import FakeKingston

TOKEN_ENV = "QISKIT_IBM_TOKEN"


class MissingTokenError(RuntimeError):
    """Raised when the real backend is requested without an IBM Quantum token."""


def get_ideal_simulator() -> AerSimulator:
    """Noiseless simulator with no coupling map."""
    return AerSimulator()


def get_fake_backend() -> FakeKingston:
    """Snapshot of IBM's Heron r2 ``ibm_kingston`` (basis gates, coupling map, noise)."""
    return FakeKingston()


def get_noisy_simulator() -> AerSimulator:
    """Aer simulator carrying FakeKingston's noise model, basis gates and coupling map."""
    return AerSimulator.from_backend(get_fake_backend())


def get_real_backend(token: str | None = None) -> BackendV2:
    """Least-busy real IBM backend. Needs a token (argument or ``QISKIT_IBM_TOKEN``)."""
    token = token or os.environ.get(TOKEN_ENV)
    if not token:
        raise MissingTokenError(
            f"No IBM Quantum token: pass one or set {TOKEN_ENV} (see .env.example)."
        )
    from qiskit_ibm_runtime import QiskitRuntimeService

    service = QiskitRuntimeService(channel="ibm_quantum_platform", token=token)
    return service.least_busy(operational=True, simulator=False)


def get_backend(kind: Literal["ideal", "noisy", "real"]) -> BackendV2:
    """Dispatch on ``kind``; unknown kinds raise ``ValueError``."""
    if kind == "ideal":
        return get_ideal_simulator()
    if kind == "noisy":
        return get_noisy_simulator()
    if kind == "real":
        return get_real_backend()
    raise ValueError(f"unknown backend kind {kind!r}; expected 'ideal', 'noisy' or 'real'")
