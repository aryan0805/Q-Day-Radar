"""Phase 1: Grover reference values and the toy SPN, independent of builder's code."""

import math
import random

import pytest

from tests.phase1.reference import grover_success, shor_theoretical_success
from tests.phase1.spn_ref import (
    SBOX,
    consistent_keys,
    encrypt,
    grover_iterations,
    make_pairs,
    perm,
)

DEMO_KEYS = {2: 0b10, 3: 0b101, 4: 0b1011, 5: 0b10110}


def test_grover_sbox_is_present_and_a_permutation():
    assert sorted(SBOX) == list(range(16))
    assert SBOX[0] == 0xC and SBOX[15] == 0x2  # PRESENT endpoints


def test_grover_spn_is_a_bijection_per_key():
    for key in range(32):
        assert sorted(encrypt(p, key) for p in range(16)) == list(range(16))


@pytest.mark.parametrize("k", [2, 3, 4, 5])
def test_grover_demo_pairs_have_exactly_one_consistent_key(k):
    assert consistent_keys(k, make_pairs(DEMO_KEYS[k])) == [DEMO_KEYS[k]]


@pytest.mark.parametrize("k", [2, 3, 4, 5])
def test_grover_every_key_is_recoverable_from_three_pairs(k):
    # M = 1 for the demo plaintexts whichever key the pairs came from
    for key in range(2**k):
        assert consistent_keys(k, make_pairs(key)) == [key], f"k={k} key={key}"


@pytest.mark.parametrize(
    ("k", "expected"),
    [(2, 1.0), (3, 0.9453125), (4, 0.961319), (5, 0.999182)],
)
def test_grover_theoretical_success_pinned(k, expected):
    j = grover_iterations(k)
    assert math.isclose(grover_success(1, 2**k, j), expected, abs_tol=1e-6)


def test_grover_iteration_counts():
    assert [grover_iterations(k) for k in (2, 3, 4, 5)] == [1, 2, 3, 4]


def test_shor_theoretical_matches_builder_cross_check():
    assert math.isclose(shor_theoretical_success(7, 15, 8), 0.5, abs_tol=1e-9)
    assert math.isclose(shor_theoretical_success(2, 21, 10), 0.33075, abs_tol=1e-5)


# ---- against builder's classical code (skipped until it exists) -----------------


def test_grover_toy_spn_matches_independent_encrypt():
    toy = pytest.importorskip("quantum.classical.toy_spn")
    for k in (2, 3, 4, 5):
        for key in range(2**k):
            for p in range(16):
                assert toy.encrypt(p, key, k) == encrypt(p, key), f"p={p} key={key} k={k}"


def test_grover_postprocess_consistent_keys_matches_independent_brute_force():
    pp = pytest.importorskip("quantum.classical.postprocess")
    rng = random.Random(7)
    for k in (2, 3, 4, 5):
        for key in [rng.randrange(2**k) for _ in range(5)]:
            pairs = make_pairs(key, (1, 6, 11))
            assert pp.consistent_keys(k, pairs) == consistent_keys(k, pairs)
            # one pair only: many keys survive; both implementations must agree on the set
            one = pairs[:1]
            assert pp.consistent_keys(k, one) == consistent_keys(k, one)
            assert all(pp.grover_key_ok(x, k, pairs) == (x == key) for x in range(2**k))


def test_grover_perm_is_rotate_left_one():
    assert [perm(x) for x in (0b0001, 0b1000, 0b1010)] == [0b0010, 0b0001, 0b0101]
