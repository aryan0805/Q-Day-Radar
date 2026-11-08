"""Independent toy-SPN reference, written from builder's spec (not from its code).

4-bit block, PRESENT S-box, P = rotate left by 1, k-bit key (2..5):
K0 = key & 0xF, K1 = P(K0) ^ (key >> 4), encrypt(p) = S(P(S(p ^ K0)) ^ K1).
"""

import math

SBOX = [0xC, 0x5, 0x6, 0xB, 0x9, 0x0, 0xA, 0xD, 0x3, 0xE, 0xF, 0x8, 0x4, 0x7, 0x1, 0x2]


def perm(x: int) -> int:
    return ((x << 1) | (x >> 3)) & 0xF


def encrypt(p: int, key: int) -> int:
    k0 = key & 0xF
    k1 = perm(k0) ^ (key >> 4)
    return SBOX[perm(SBOX[p ^ k0]) ^ k1]


def make_pairs(key: int, plaintexts: tuple[int, ...] = (1, 6, 11)) -> list[tuple[int, int]]:
    return [(p, encrypt(p, key)) for p in plaintexts]


def consistent_keys(key_bits: int, pairs: list[tuple[int, int]]) -> list[int]:
    return [k for k in range(2**key_bits) if all(encrypt(p, k) == c for p, c in pairs)]


def grover_iterations(key_bits: int) -> int:
    return math.floor(math.pi / 4 * math.sqrt(2**key_bits))
