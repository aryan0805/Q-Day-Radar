"""Grover key search on the toy 2-round SPN with the PRESENT S-box (k = 2..5 key bits).

Label: ``generic``. The builder takes the key size and the (plaintext, ciphertext) pairs only.
It never sees a key, never calls ``encrypt`` and never loops over candidate keys: the oracle
works out the cipher reversibly on the key qubits, and the ciphertext appears only as X gates
that set the comparison target. Cipher spec: ``quantum/classical/toy_spn.py``
(``c = S(P(S(p ^ K0)) ^ K1)``, ``K0 = key & 0xF``, ``K1 = P(K0) ^ (key >> 4)``).

Registers: ``kq`` (k key qubits, qubit i = key bit i), ``w`` (4 work qubits shared by every
pair), and for n >= 2 pairs ``flag`` (n - 1 qubits) plus ``tmp`` (1 qubit). Every ancilla
starts and ends in |0>. Width = k + 4 for one pair, k + n + 4 otherwise (12 for k=5, n=3). One
classical register ``key``: clbit i = key bit i, so ``int(bitstring, 2)`` is the key.

What one pair (p, c) computes on w (wire j = bit j), given that w already holds K0:
1. ``X`` where p has a 1: w = p ^ K0.
2. The S-box in place on w: 4 Toffolis + 10 CNOTs (``SBOX_GATES``). It was found offline by a
   meet-in-the-middle search over decompositions of the public S-box. PRESENT's S-box has
   multiplicative complexity 4, so 4 Toffolis is the minimum. The gates only couple the line
   w0-w1-w2-w3, so the S-box on its own fits a heavy-hex line with no SWAPs. A 5-CNOT version
   exists, but its interaction graph is K4 and it ends up with about 12% more 2-qubit gates
   after routing for FakeKingston. ``_check_sbox_gates`` proves at import time that the gate
   list equals ``SBOX``.
   For k < 4, wires j >= k hold plaintext bits, which are classical constants. Those constants
   are folded through the gate list: a Toffoli with a known control becomes a CNOT or nothing.
   This is partial evaluation on the public plaintext, the same for every key.
3. ``CX(kq[j] -> w[j])`` for j < min(k, 4), and ``CX(kq[4] -> w[3])`` when k = 5. Because P is
   linear, ``P(S(.)) ^ K1 = P(S(.) ^ K0 ^ k4*e3)``. So w now holds ``P^-1`` of the second S-box
   input and P itself is only a relabelling of wires.
4. Comparison. The last S-box has no key after it, so ``S(x2) == c`` iff ``x2 == S^-1(c)``.
   With the default ``peel_last_sbox=True`` the target is the public constant
   ``P^-1(S^-1(c))``. With ``peel_last_sbox=False`` the second S-box is computed forward instead
   (the same gate list on the wires relabelled by P) and compared with c directly. Both mark
   the same keys. In both cases X gates flip the wires whose target bit is 0, so all 4 wires read
   1 iff the pair matches.

Oracle: copy K0 into w, then, for each pair but the last: compute it, AND its 4 match bits
into ``flag[i]`` (RCCX . RC3X . RCCX through ``tmp``), and uncompute it. Then compute the last
pair, apply one exact multi-controlled Z on (flags + w), and undo everything in reverse. The Z
fires iff every pair matches, i.e. it marks exactly ``consistent_keys(k, pairs)``. Every
Toffoli is a relative-phase gate (RCCX / RC3X). The whole oracle has the form
``W^dagger . MCZ . W``, where W is built only from X, CX, RCCX and RC3X, so W is a
permutation times a diagonal. Since the MCZ is diagonal, that form is exactly the phase oracle,
with every relative phase cancelled. The transpiler borrows idle qubits as dirty ancillas for
the MCZ. Keeping all pairs live at once (4 qubits each, no flags) uses fewer logical gates, but
it needs k + 4n qubits and ended up with about 30% more 2-qubit gates after routing for
FakeKingston (measured with the K4 S-box).

Diffusion is the standard ``H X (MCZ) X H`` on the key register. ``default_iterations`` assumes
M = 1, like a real attacker who does not know how many keys are consistent.
"""

from __future__ import annotations

import math

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

from quantum.classical.toy_spn import SBOX

KEY_BITS_RANGE = (2, 3, 4, 5)

# In-place PRESENT S-box on 4 wires (wire j = bit j): ("ccx", a, b, t), ("cx", c, t), ("x", q).
# Interaction graph is the line 0-1-2-3: CNOTs act on neighbours only, and every Toffoli's
# target sits between its two controls (RCCX only couples control -> target).
SBOX_GATES: tuple[tuple[str | int, ...], ...] = (
    ("cx", 2, 1),
    ("cx", 2, 3),
    ("ccx", 1, 3, 2),
    ("x", 0),
    ("x", 2),
    ("ccx", 0, 2, 1),
    ("x", 2),
    ("cx", 1, 2),
    ("cx", 3, 2),
    ("cx", 2, 3),
    ("x", 2),
    ("ccx", 1, 3, 2),
    ("x", 3),
    ("x", 1),
    ("cx", 2, 3),
    ("cx", 0, 1),
    ("cx", 1, 0),
    ("cx", 2, 1),
    ("cx", 1, 0),
    ("ccx", 1, 3, 2),
)


def _run_sbox_gates(x: int) -> int:
    """Classically evaluate ``SBOX_GATES`` on the 4-bit input ``x``."""
    b = [(x >> i) & 1 for i in range(4)]
    for op, *q in SBOX_GATES:
        if op == "x":
            b[q[0]] ^= 1
        elif op == "cx":
            b[q[1]] ^= b[q[0]]
        else:
            b[q[2]] ^= b[q[0]] & b[q[1]]
    return sum(v << i for i, v in enumerate(b))


def _check_sbox_gates() -> None:
    table = tuple(_run_sbox_gates(x) for x in range(16))
    if table != SBOX:
        raise AssertionError(f"SBOX_GATES implements {table}, not the PRESENT S-box {SBOX}")


_check_sbox_gates()


def default_iterations(key_bits: int) -> int:
    """floor(pi/4 * sqrt(2**k)): the optimal count when exactly one key is marked (M = 1)."""
    _check_key_bits(key_bits)
    return math.floor(math.pi / 4 * math.sqrt(2**key_bits))


def _check_key_bits(key_bits: int) -> None:
    if key_bits not in KEY_BITS_RANGE:
        raise ValueError(f"key_bits must be in 2..5, got {key_bits}")


def _check_pairs(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    pairs = [(int(pt), int(ct)) for pt, ct in pairs]
    if not pairs:
        raise ValueError("need at least one (plaintext, ciphertext) pair")
    for pt, ct in pairs:
        if not (0 <= pt < 16 and 0 <= ct < 16):
            raise ValueError(f"pair {(pt, ct)} is not two 4-bit values")
    return pairs


def _inv_perm(x: int) -> int:
    """P^-1: rotate a 4-bit value right by one."""
    return ((x >> 1) | (x << 3)) & 0xF


def _append_sbox(qc: QuantumCircuit, wires: list, const: list[int | None]) -> None:
    """In-place S-box on ``wires`` (wires[j] = bit j); Toffolis as relative-phase RCCX.

    ``const[j]`` is the known classical value of wires[j] (None if it depends on the key). It
    is updated in place. A gate whose control is a known 0 is dropped. A known 1 control turns
    CX into X and RCCX into CX.
    """
    for op, *q in SBOX_GATES:
        if op == "x":
            qc.x(wires[q[0]])
            if const[q[0]] is not None:
                const[q[0]] ^= 1
            continue
        *controls, t = q
        live = [c for c in controls if const[c] is None]
        if any(const[c] == 0 for c in controls):
            continue
        if not live:
            qc.x(wires[t])
            if const[t] is not None:
                const[t] ^= 1
            continue
        if len(live) == 1:
            qc.cx(wires[live[0]], wires[t])
        else:
            qc.rccx(wires[live[0]], wires[live[1]], wires[t])
        const[t] = None


def _pair_core(
    key_bits: int,
    pt: int,
    ct: int,
    regs: list,
    kq: QuantumRegister,
    w: QuantumRegister,
    peel_last_sbox: bool,
) -> QuantumCircuit:
    """Map w = K0 to the pair's 4 match bits (all 1 iff encrypt(pt, key) == ct)."""
    qc = QuantumCircuit(*regs)
    low = min(key_bits, 4)
    const: list[int | None] = [None if j < low else 0 for j in range(4)]
    for j in range(4):  # w = pt ^ K0
        if (pt >> j) & 1:
            qc.x(w[j])
            if const[j] is not None:
                const[j] ^= 1
    _append_sbox(qc, list(w), const)  # w = S(pt ^ K0)
    for j in range(low):  # w = S(.) ^ K0
        qc.cx(kq[j], w[j])
        const[j] = None
    if key_bits == 5:  # ^ k4 * e3 = P^-1(k4 * e0): now w = P^-1(x2), x2 = input of 2nd S-box
        qc.cx(kq[4], w[3])
        const[3] = None
    if peel_last_sbox:
        target, wire_of_bit = _inv_perm(SBOX.index(ct)), list(w)
    else:
        order = [(i - 1) % 4 for i in range(4)]  # x2 bit i sits on w[i-1] (P relabel)
        wire_of_bit = [w[j] for j in order]
        const2 = [const[j] for j in order]
        _append_sbox(qc, wire_of_bit, const2)  # bit i of S(x2) on wire_of_bit[i]
        target = ct
    for i in range(4):  # wire reads 1 iff its bit matches the target
        if not (target >> i) & 1:
            qc.x(wire_of_bit[i])
    return qc


def _append_mcz(qc: QuantumCircuit, qubits: list) -> None:
    *controls, target = qubits
    qc.h(target)
    qc.mcx(controls, target)
    qc.h(target)


def _registers(key_bits: int, n_pairs: int) -> list:
    regs = [QuantumRegister(key_bits, "kq"), QuantumRegister(4, "w")]
    if n_pairs > 1:
        regs += [QuantumRegister(n_pairs - 1, "flag"), QuantumRegister(1, "tmp")]
    return regs


def build_oracle(
    key_bits: int, pairs: list[tuple[int, int]], *, peel_last_sbox: bool = True
) -> QuantumCircuit:
    """Phase oracle on ``kq`` (qubits 0..k-1) plus ancillas that start and end in |0>.

    Maps |key>|0> to -|key>|0> iff the key is consistent with every pair, else +|key>|0>.
    """
    _check_key_bits(key_bits)
    pairs = _check_pairs(pairs)
    regs = _registers(key_bits, len(pairs))
    kq, w = regs[0], regs[1]
    flags, tmp = (regs[2], regs[3][0]) if len(pairs) > 1 else (None, None)

    W = QuantumCircuit(*regs)  # everything before the central MCZ
    for j in range(min(key_bits, 4)):  # w = K0
        W.cx(kq[j], w[j])
    for i, (pt, ct) in enumerate(pairs[:-1]):
        core = _pair_core(key_bits, pt, ct, regs, kq, w, peel_last_sbox)
        W.compose(core, inplace=True)
        W.rccx(w[0], w[1], tmp)  # flag[i] ^= AND(match bits), up to a relative phase
        W.rcccx(tmp, w[2], w[3], flags[i])
        W.rccx(w[0], w[1], tmp)
        W.compose(core.inverse(), inplace=True)
    pt, ct = pairs[-1]
    W.compose(_pair_core(key_bits, pt, ct, regs, kq, w, peel_last_sbox), inplace=True)

    oracle = QuantumCircuit(*regs, name="oracle")
    oracle.compose(W, inplace=True)
    _append_mcz(oracle, (list(flags) if flags is not None else []) + list(w))
    oracle.compose(W.inverse(), inplace=True)
    return oracle


def _append_diffusion(qc: QuantumCircuit, kq: QuantumRegister) -> None:
    qc.h(kq)
    qc.x(kq)
    _append_mcz(qc, list(kq))
    qc.x(kq)
    qc.h(kq)


def build_grover(
    key_bits: int,
    pairs: list[tuple[int, int]],
    iterations: int | None = None,
    *,
    peel_last_sbox: bool = True,
) -> QuantumCircuit:
    """Grover search for the keys consistent with ``pairs``; measures register ``key``."""
    _check_key_bits(key_bits)
    pairs = _check_pairs(pairs)
    if iterations is None:
        iterations = default_iterations(key_bits)
    if iterations < 0:
        raise ValueError("iterations must be >= 0")
    oracle = build_oracle(key_bits, pairs, peel_last_sbox=peel_last_sbox)
    regs = _registers(key_bits, len(pairs))
    key = ClassicalRegister(key_bits, "key")
    qc = QuantumCircuit(*regs, key, name=f"grover_present_k{key_bits}")
    kq = regs[0]
    qc.h(kq)
    for _ in range(iterations):
        qc.compose(oracle, inplace=True)
        _append_diffusion(qc, kq)
    qc.measure(kq, key)
    qc.metadata = {
        "name": f"grover_present_k{key_bits}",
        "kind": "generic",
        "key_bits": key_bits,
        "pairs": pairs,
        "iterations": iterations,
        "peel_last_sbox": peel_last_sbox,
    }
    return qc
