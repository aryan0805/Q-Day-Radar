"""Generic Beauregard Shor circuit (2n+3 qubits, semi-classical QFT). Label: ``generic``.

``build_shor(N, a)`` takes only the modulus and the base. It never computes, reads or receives
the order of ``a``, the factors of ``N`` or anything derived from them. All classical
precomputation is on the constants Beauregard's construction needs anyway: the multipliers
``A_p = a**(2**p) mod N``, their inverses ``pow(A_p, -1, N)``, the addends ``(2**i * A_p) mod N``
and (window, item 4 below) sums of at most three of those addends.

Layout (n = N.bit_length(), m = n + 1, 2n+3 qubits in total)::

    b    m qubits  accumulator, kept in Draper (QFT) space; in the computational basis b[0] is
                   the LSB and b[n] the sign/overflow bit. b[0]-b[1]-...-b[n] is a line.
    x    n qubits  work register, starts in |1>, holds a**k mod N; x[0] is the LSB
    anc  1 qubit   overflow flag / scratch AND bit (clean |0> between additions)
    ctrl 1 qubit   the single recycled phase-estimation control

Classical register: ONE register ``phase`` of 2n bits. Clbit j holds the phase bit of weight
2**j, so ``int(bitstring, 2)`` is the usual QPE integer m with m / 2**(2n) ~ s / r, the same
convention as ``shor_textbook``.

Semi-classical QFT (Griffiths-Niu): one control qubit replaces the 2n counting qubits and the
inverse QFT. Iteration i (i = 0 .. 2n-1) prepares ctrl in |+>, applies C-U with power
2**(2n-1-i), so the first iteration reads the least significant phase bit. For every earlier
bit k measured as 1 (``if_test`` on clbit ``phase[k]``) it applies ``P(-pi / 2**(i-k))``, which
is the inverse QFT's controlled phase with a classical control. Then H, measure into
``phase[i]``, and ``reset`` ctrl for the next iteration.

Arithmetic (Beauregard, quant-ph/0205095):

* QFT: Qiskit's nearest-neighbour ``synth_qft_line`` (3 CX per qubit pair along the b line),
  which also reverses the register. In Fourier space, b[n-j] therefore carries
  exp(2 pi i v / 2**(j+1)).
* ``phi_add(k)``: adding a classical constant in Fourier space is one phase gate per qubit,
  ``P(2 pi k / 2**(j+1))`` on Fourier qubit j. Constants are folded into the angles.
* ``c_phi_add(k)`` (one control): the m controlled phases are a phase polynomial in
  c * b_j = (c + b_j - c XOR b_j) / 2. A nearest-neighbour CX ladder (2m - 1 CX) writes
  c XOR b_j onto every b_j, one phase each, then the same ladder undoes it.
* ``add_mod(k)``: doubly controlled (b + k) mod N. Steps 1-4 are Beauregard's (add k, subtract
  N, copy the sign bit to ``anc``, add N back under ``anc``). Steps 5-7 subtract and re-add k
  WITHOUT controls and clear ``anc`` by ``anc ^= ctrl x[i] sign`` then NOT (one C3X instead of
  two doubly controlled additions; when ctrl x[i] = 0 the flag is always 1).
* ``cmult(A)``: |c>|x>|0> -> |c>|x>|A x mod N> (if c), adding ``2**i A mod N`` under (c, x[i]).
* C-U_A: ``cmult(A)``, controlled swap of x with b[0:n], then ``cmult(A**-1)`` inverted.

Gate-count reductions, all exact:

1. ``b`` is |0> when each multiplier starts, so its opening QFT is H on every qubit.
2. A doubly or triply controlled addition made while ``anc`` is clean computes the AND of its
   controls into ``anc`` with a relative-phase Toffoli (RCCX, 3 CX; RC3X, 6 CX), adds under
   ``anc`` alone and uncomputes. Each of those gates is a permutation times a diagonal and
   everything in between is diagonal, so the relative phases cancel exactly.
3. Term 0 of a multiplier adds k0 < N to b = 0, which never overflows: no comparator.
4. Window of three terms (``fold_constants=True``): before term i <= 2 the accumulator holds
   s(x_<i) = (sum_{j<i} k_j x_j) mod N, a function of at most two x bits. Whether adding k_i
   overflows is the classical truth table f_i(x_<i) = [s + k_i >= N] (at most four sums of
   constants), so the reduction is "subtract N if ctrl AND x[i] AND f_i(x_<i)". Terms 3 .. n-1
   use the comparator-based ``add_mod``. This is a 3-bit version of windowed arithmetic
   (Gidney, arXiv:1905.07682).
5. Controlled load (``fold_constants=True``): while x still holds exactly |1> (nothing applied
   yet) C-U_A is the controlled load |1> -> |A>, CX gates from ctrl onto the bits of 1 XOR A.
   This is the same for every A, so it does not depend on the order.

``fold_constants=False`` turns off 4 and 5: every one of the 2n controlled multipliers is
built in full and terms 1 .. n-1 all use ``add_mod``. Use it for audits.

Honesty note (P003): the default build applies one controlled multiplier per iteration, for
every iteration (the first as the load, then 2n-1 full multipliers), whatever a**(2**p) mod N
is. Dropping multipliers that happen to equal 1 mod N would bake the order into the circuit
(Smolin, Smith, Vargo, arXiv:1301.7007), so it is an explicit opt-in, ``skip_identity=True``,
and a circuit built that way is labelled ``compiled``, not ``generic``.
"""

from __future__ import annotations

from functools import cache
from math import gcd, pi

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit import Qubit
from qiskit.circuit.library import RC3XGate, RCCXGate
from qiskit.synthesis import synth_qft_line

Qubits = list[Qubit]


def _angles(k: int, m: int) -> list[float]:
    """Draper phases for adding the constant ``k``: Fourier qubit j gets 2 pi k / 2**(j+1).

    Only k mod 2**(j+1) matters; angles are reduced to (-pi, pi].
    """
    out = []
    for j in range(m):
        mod = 2 ** (j + 1)
        r = k % mod
        if 2 * r > mod:
            r -= mod
        out.append(2 * pi * r / mod)
    return out


def _fourier(b: Qubits) -> Qubits:
    """b in Fourier-index order: element j carries exp(2 pi i v / 2**(j+1)) after ``_qft``."""
    return b[::-1]


@cache
def _qft_line(m: int) -> tuple[QuantumCircuit, QuantumCircuit]:
    qft = synth_qft_line(m, do_swaps=True)  # QFT followed by a reversal, nearest-neighbour
    return qft, qft.inverse()


def _qft(qc: QuantumCircuit, b: Qubits) -> None:
    qc.compose(_qft_line(len(b))[0], qubits=b, inplace=True)


def _iqft(qc: QuantumCircuit, b: Qubits) -> None:
    qc.compose(_qft_line(len(b))[1], qubits=b, inplace=True)


def _phi_add(qc: QuantumCircuit, b: Qubits, k: int) -> None:
    for q, th in zip(_fourier(b), _angles(k, len(b)), strict=True):
        if th:
            qc.p(th, q)


def _c_phi_add(qc: QuantumCircuit, b: Qubits, k: int, c: Qubit) -> None:
    """Add k under control c, as a phase polynomial with a nearest-neighbour CX ladder.

    exp(i th c t) = exp(i th/2 c) exp(i th/2 t) exp(-i th/2 (c XOR t)). The ladder runs along
    c - t[0] - t[1] - ..., with t = Fourier order (t[0] = b[n], the sign bit next to anc), and
    maps every t[j] to t[j] XOR c. It is an involution, so running it again undoes it.
    """
    t = _fourier(b)
    th = _angles(k, len(b))
    if not any(th):
        return

    def ladder() -> None:
        for j in reversed(range(1, len(t))):
            qc.cx(t[j - 1], t[j])
        qc.cx(c, t[0])
        for j in range(1, len(t)):
            qc.cx(t[j - 1], t[j])

    qc.p(sum(th) / 2, c)
    for q, a in zip(t, th, strict=True):
        if a:
            qc.p(a / 2, q)
    ladder()
    for q, a in zip(t, th, strict=True):
        if a:
            qc.p(-a / 2, q)
    ladder()


def _mc_phi_add_clean(qc: QuantumCircuit, b: Qubits, k: int, controls: Qubits, anc: Qubit) -> None:
    """Add k if both or all three controls are 1. ``anc`` must be |0>; it holds the AND."""
    gate = {2: RCCXGate(), 3: RC3XGate()}[len(controls)]
    qc.append(gate, [*controls, anc])
    _c_phi_add(qc, b, k, anc)
    qc.append(gate.inverse(), [*controls, anc])


def _flag_circuit(
    qc: QuantumCircuit,
    c: Qubit,
    xi: Qubit,
    prev: Qubits,
    table: list[int],
    anc: Qubit,
    dirty: Qubit,
) -> QuantumCircuit | None:
    """Circuit V whose permutation part is anc ^= c AND xi AND f(prev); f is ``table``.

    ``table[v]`` is f at prev = bits of v (prev[0] = LSB), with len(prev) <= 2 and f(0) = 0.
    V uses only CX, X, RCCX and RC3X, so V is a permutation times a diagonal: V^-1 undoes its
    phases exactly. ``dirty`` may be in any state; V restores it. None if f is identically 0.
    """
    if not any(table):
        return None
    v = QuantumCircuit(*qc.qregs)
    if len(prev) == 1 or table[3] == table[1] ^ table[2]:  # affine: f = XOR of some prev bits
        used = [q for j, q in enumerate(prev) if table[1 << j]]
        for q in used[1:]:
            v.cx(q, used[0])
        v.append(RC3XGate(), [c, xi, used[0], anc])
        for q in used[1:]:
            v.cx(q, used[0])
        return v
    # Non-affine f of two bits with f(0) = 0 is f = q XOR (x0 XOR p0)(x1 XOR p1), q = p0 p1.
    p0, p1 = table[2], table[1]
    flips = [q for q, pol in zip(prev, (p0, p1), strict=True) if pol]
    compute = QuantumCircuit(*qc.qregs)  # dirty ^= f(prev), up to a diagonal phase
    for q in flips:
        compute.x(q)
    compute.append(RCCXGate(), [prev[0], prev[1], dirty])
    for q in flips:
        compute.x(q)
    if p0 and p1:
        compute.x(dirty)
    for _ in range(2):  # anc ^= c xi (d ^ f), then anc ^= c xi d: net anc ^= c xi f
        v.compose(compute, inplace=True)
        v.append(RC3XGate(), [c, xi, dirty, anc])
    return v


def _add_mod(
    qc: QuantumCircuit, b: Qubits, k: int, N: int, c1: Qubit, c2: Qubit, anc: Qubit
) -> None:
    """Doubly controlled Fourier-space (b + k) mod N. Needs 0 <= b < N, 0 <= k < N, anc |0>.

    With c1 c2 = 1, sign(b' - k) = NOT flag, as in Beauregard. With c1 c2 = 0 the flag is always
    1 (b - N < 0) and the final NOT alone clears it.
    """
    msb = b[-1]
    _mc_phi_add_clean(qc, b, k, [c1, c2], anc)  # 1. b + k c1 c2
    _phi_add(qc, b, -N)  # 2. minus N
    _iqft(qc, b)  # 3. flag = sign bit = [b + k c1 c2 < N]
    qc.cx(msb, anc)
    _qft(qc, b)
    _c_phi_add(qc, b, N, anc)  # 4. add N back if negative: b' = (b + k c1 c2) mod N
    _phi_add(qc, b, -k)  # 5. b' - k, uncontrolled
    _iqft(qc, b)  # 6. flag ^= c1 c2 sign, then NOT: flag is |0> again
    qc.mcx([c1, c2, msb], anc)
    qc.x(anc)
    _qft(qc, b)
    _phi_add(qc, b, k)  # 7. back to b', uncontrolled


def _cmult(
    qc: QuantumCircuit,
    b: Qubits,
    x: Qubits,
    A: int,
    N: int,
    c: Qubit,
    anc: Qubit,
    *,
    fold_constants: bool,
) -> None:
    """|c>|x>|b=0> -> |c>|x>|A x mod N> when c=1 (b untouched when c=0)."""
    for q in b:  # QFT|0> = H on every qubit
        qc.h(q)
    k = [(A * 2**i) % N for i in range(len(x))]
    n_window = min(len(x), 3) if fold_constants else 1
    for i in range(n_window):
        _mc_phi_add_clean(qc, b, k[i], [c, x[i]], anc)
        table = [
            int(sum(k[j] for j in range(i) if v >> j & 1) % N + k[i] >= N) for v in range(2**i)
        ]
        dirty = [*x[i + 1 :], *b][0]
        flag = _flag_circuit(qc, c, x[i], list(x[:i]), table, anc, dirty)
        if flag is not None:
            qc.compose(flag, inplace=True)
            _c_phi_add(qc, b, -N, anc)
            qc.compose(flag.inverse(), inplace=True)
    for i in range(n_window, len(x)):
        _add_mod(qc, b, k[i], N, c, x[i], anc)
    _iqft(qc, b)


def _controlled_mult(
    qc: QuantumCircuit,
    b: Qubits,
    x: Qubits,
    A: int,
    N: int,
    c: Qubit,
    anc: Qubit,
    *,
    fold_constants: bool = True,
) -> None:
    """|c>|x>|0> -> |c>|A x mod N>|0> when c=1. ``A`` must be invertible mod N."""
    _cmult(qc, b, x, A, N, c, anc, fold_constants=fold_constants)
    for xq, bq in zip(x, b[: len(x)], strict=True):
        qc.cswap(c, xq, bq)
    undo = QuantumCircuit(*qc.qregs)
    _cmult(undo, b, x, pow(A, -1, N), N, c, anc, fold_constants=fold_constants)
    qc.compose(undo.inverse(), inplace=True)


def build_shor(
    N: int, a: int, *, fold_constants: bool = True, skip_identity: bool = False
) -> QuantumCircuit:
    """Order-finding circuit for ``a`` mod ``N``: 2n+3 qubits, one register ``phase`` of 2n bits.

    Inputs are only N and a. ``fold_constants`` picks optimisations; ``skip_identity=True``
    drops multipliers equal to 1 and makes the circuit ``compiled`` (see the module docstring).
    """
    if N < 3:
        raise ValueError(f"N must be >= 3, got {N}")
    if not 1 < a < N:
        raise ValueError(f"need 1 < a < N, got a={a}, N={N}")
    if gcd(a, N) != 1:
        raise ValueError(f"a={a} is not coprime to N={N}")

    n = N.bit_length()
    n_count = 2 * n
    b = QuantumRegister(n + 1, "b")
    x = QuantumRegister(n, "x")
    anc = QuantumRegister(1, "anc")
    ctrl = QuantumRegister(1, "ctrl")
    phase = ClassicalRegister(n_count, "phase")
    qc = QuantumCircuit(b, x, anc, ctrl, phase, name=f"shor{N}_beauregard")
    bq, xq, aq, cq = list(b), list(x), anc[0], ctrl[0]

    multipliers = [a]  # A_p = a**(2**p) mod N by repeated squaring
    for _ in range(n_count - 1):
        multipliers.append(multipliers[-1] ** 2 % N)

    qc.x(xq[0])
    x_is_one = True  # x still holds exactly |1>: no multiplication applied yet
    for i in range(n_count):
        A = multipliers[n_count - 1 - i]
        if i:
            qc.reset(cq)
        qc.h(cq)
        if skip_identity and A == 1:
            pass  # opt-in, order-dependent: the circuit is then `compiled`
        elif fold_constants and x_is_one:
            for j in range(n):  # controlled load |1> -> |A>
                if (1 ^ A) >> j & 1:
                    qc.cx(cq, xq[j])
            x_is_one = False
        else:
            _controlled_mult(qc, bq, xq, A, N, cq, aq, fold_constants=fold_constants)
            x_is_one = False
        for k in range(i):  # semi-classical inverse QFT: classically controlled phases
            with qc.if_test((phase[k], 1)):
                qc.p(-pi / 2 ** (i - k), cq)
        qc.h(cq)
        qc.measure(cq, phase[i])

    qc.metadata = {
        "name": f"shor{N}_beauregard",
        "kind": "compiled" if skip_identity else "generic",
        "N": N,
        "a": a,
        "n_count": n_count,
    }
    return qc
