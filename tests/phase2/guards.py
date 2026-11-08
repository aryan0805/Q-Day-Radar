"""Shared helpers for the phase-2 safety net (one module name for conftest and the tests)."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKEN_VARS = (
    "QISKIT_IBM_TOKEN",
    "QISKIT_IBM_INSTANCE",
    "QISKIT_IBM_CHANNEL",
    "QISKIT_IBM_URL",
    "IBM_QUANTUM_TOKEN",
)


def tree_digest(*paths: Path) -> str:
    """sha256 over (relative path, bytes) of every file under ``paths`` (missing paths count)."""
    h = hashlib.sha256()
    for base in paths:
        files = [base] if base.is_file() else sorted(base.rglob("*")) if base.exists() else []
        h.update(f"{base}:{'present' if base.exists() else 'absent'}".encode())
        for f in files:
            if f.is_file():
                h.update(str(f.relative_to(base) if base.is_dir() else f.name).encode())
                h.update(f.read_bytes())
    return h.hexdigest()


class NetworkAccessError(AssertionError):
    pass
