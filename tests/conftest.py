"""Shared fixtures. Owned by reviewer."""

import pytest

SEED = 1234


@pytest.fixture
def seed() -> int:
    """Fixed seed for seed_simulator / seed_transpiler so tests are deterministic."""
    return SEED
