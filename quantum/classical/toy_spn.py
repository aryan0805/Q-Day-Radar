"""Toy 2-round substitution-permutation network used by the Grover circuits.

Spec (the reviewer re-implements this independently in tests/phase1):
- Block: 4 bits. S-box: PRESENT, S = [C,5,6,B,9,0,A,D,3,E,F,8,4,7,1,2].
- Permutation layer P: rotate the 4-bit block left by 1 (bit i -> bit (i+1) mod 4).
- Key: ``key_bits`` = k in 2..5 bits, an integer in [0, 2**k).
  K0 = key & 0xF            (zero-extended when k < 4)
  K1 = P(K0) ^ (key >> 4)   (the 5th key bit, when k = 5, flips bit 0 of K1; else key >> 4 = 0)
- encrypt(p) = S( P( S(p ^ K0) ) ^ K1 )
"""

from __future__ import annotations

SBOX = (0xC, 0x5, 0x6, 0xB, 0x9, 0x0, 0xA, 0xD, 0x3, 0xE, 0xF, 0x8, 0x4, 0x7, 0x1, 0x2)


def perm(x: int) -> int:
    """Rotate a 4-bit value left by one."""
    return ((x << 1) | (x >> 3)) & 0xF


def round_keys(key: int, key_bits: int) -> tuple[int, int]:
    if not 2 <= key_bits <= 5 or not 0 <= key < 2**key_bits:
        raise ValueError(f"key {key} does not fit in {key_bits} bits (2..5 supported)")
    k0 = key & 0xF
    return k0, perm(k0) ^ (key >> 4)


def encrypt(plaintext: int, key: int, key_bits: int) -> int:
    k0, k1 = round_keys(key, key_bits)
    return SBOX[perm(SBOX[(plaintext & 0xF) ^ k0]) ^ k1]
