"""Phase 1 unit 5: Grover on the toy PRESENT SPN (kind=generic).

Expected values come from tests/phase1/spn_ref.py and reference.py, never from builder's
encrypt / consistent_keys. The oracle is checked EXACTLY: |key>|0..0> must go to
+-|key>|0..0> with sign -1 iff key is consistent (so no leftover relative phase, ancillas
returned to |0>).
"""

import ast
import inspect
import itertools
import json
import math
import random

import pytest
from qiskit import transpile
from qiskit.quantum_info import Statevector
from qiskit_aer import AerSimulator

from quantum.circuits import grover_present, registry
from quantum.circuits.grover_present import build_grover, build_oracle, default_iterations
from quantum.metrics import record_circuit_metrics
from tests.phase1.reference import grover_chance_baseline, grover_success
from tests.phase1.spn_ref import consistent_keys, grover_iterations, make_pairs

SHOTS = 8192
DEMO_PT = (1, 6, 11)
KS = (2, 3, 4, 5)


def _simulate(qc, seed=1234):
    sim = AerSimulator(seed_simulator=seed)
    return sim.run(transpile(qc, sim, optimization_level=0), shots=SHOTS).result().get_counts()


def _mass_on(counts, keys):
    return sum(n for b, n in counts.items() if int(b, 2) in keys) / SHOTS


def _all_pairs_necessary(k, key, n_pairs):
    """Plaintext sets where dropping ANY one pair enlarges the consistent set."""
    out = []
    for pts in itertools.combinations(range(16), n_pairs):
        pairs = make_pairs(key, pts)
        full = set(consistent_keys(k, pairs))
        if all(
            set(consistent_keys(k, pairs[:i] + pairs[i + 1 :])) > full for i in range(n_pairs)
        ):
            out.append(pts)
    return out


NECESSARY_CASES = [
    (k, key, n, _all_pairs_necessary(k, key, n)[0])
    for k, key, n in [(3, 5, 2), (4, 6, 2), (5, 22, 3), (5, 9, 3)]
    if _all_pairs_necessary(k, key, n)
]


def _assert_oracle_exact(k, pairs, peel):
    oracle = build_oracle(k, pairs, peel_last_sbox=peel)
    marked = set(consistent_keys(k, pairs))
    n = oracle.num_qubits
    for key in range(2**k):
        out = Statevector.from_int(key, 2**n).evolve(oracle)
        amp = out.data[key]  # kq = qubits 0..k-1, every ancilla |0>
        want = -1.0 if key in marked else 1.0
        assert abs(amp - want) < 1e-9, f"k={k} key={key} peel={peel} amp={amp} want={want}"


# ---- oracle truth table ---------------------------------------------------------------


@pytest.mark.parametrize("peel", [True, False])
@pytest.mark.parametrize("k", KS)
def test_grover_oracle_marks_exactly_the_consistent_key_demo_pairs(k, peel):
    key = random.Random(k).randrange(2**k)
    pairs = make_pairs(key, DEMO_PT)
    assert consistent_keys(k, pairs) == [key]
    _assert_oracle_exact(k, pairs, peel)


@pytest.mark.parametrize("peel", [True, False])
@pytest.mark.parametrize(
    ("k", "plaintexts"),
    [
        (2, (5,)),  # one pair: no flag register, M may be > 1
        (3, (0, 15)),  # two pairs
        (4, (3,)),
        (4, (2, 9, 12, 7)),  # four pairs
        (3, (4, 4)),  # duplicate pair
    ],
)
def test_grover_oracle_truth_table_other_plaintext_sets(k, plaintexts, peel):
    key = random.Random(hash((k, plaintexts)) & 0xFFFF).randrange(2**k)
    pairs = make_pairs(key, plaintexts)
    assert key in consistent_keys(k, pairs)
    _assert_oracle_exact(k, pairs, peel)


@pytest.mark.parametrize("peel", [True, False])
@pytest.mark.parametrize(("k", "key", "n", "plaintexts"), NECESSARY_CASES)
def test_grover_oracle_every_pair_matters(k, key, n, plaintexts, peel):
    # a flag wired wrongly for any one pair would mark extra keys here
    pairs = make_pairs(key, plaintexts)
    assert key in consistent_keys(k, pairs)
    _assert_oracle_exact(k, pairs, peel)


def test_grover_necessary_pair_cases_cover_two_and_three_pair_flag_wiring():
    # for k <= 4 two pairs always fix the key, so 3 necessary pairs only exist at k = 5
    assert {(k, n) for k, _, n, _ in NECESSARY_CASES} >= {(3, 2), (4, 2), (5, 3)}


def test_grover_oracle_with_no_consistent_key_marks_nothing():
    k = 3
    pairs = [(1, 0), (1, 1)]  # same plaintext, two ciphertexts: impossible
    assert consistent_keys(k, pairs) == []
    _assert_oracle_exact(k, pairs, True)


def test_grover_oracle_multiple_consistent_keys_marked():
    k = 4
    pairs = make_pairs(5, (0,))  # one pair leaves several keys
    assert len(consistent_keys(k, pairs)) > 1
    _assert_oracle_exact(k, pairs, True)


# ---- the algorithm on the ideal simulator ---------------------------------------------


@pytest.mark.parametrize("k", KS)
def test_grover_demo_circuit_finds_the_key_with_theoretical_probability(k):
    qc = registry.build_circuit(f"grover_present_k{k}")
    pairs = qc.metadata["pairs"]
    keys = consistent_keys(k, pairs)
    assert len(keys) == 1
    j = qc.metadata["iterations"]
    assert j == grover_iterations(k)
    theory = grover_success(1, 2**k, j)
    counts = _simulate(qc)
    got = _mass_on(counts, set(keys))
    assert got >= theory - 0.02, f"k={k}: {got} vs {theory}"
    assert max(counts, key=counts.get) == format(keys[0], f"0{k}b")


@pytest.mark.parametrize("k", KS)
def test_grover_amplitude_follows_sin_squared_not_a_constant(k):
    # one fewer / one more iteration must change the success the way sin^2 predicts
    pairs = registry.grover_pairs(k)
    j = grover_iterations(k)
    for it in sorted({max(j - 1, 0), j + 1}):
        counts = _simulate(build_grover(k, pairs, iterations=it))
        want = grover_success(1, 2**k, it)
        got = _mass_on(counts, set(consistent_keys(k, pairs)))
        assert abs(got - want) < 0.03, f"k={k} it={it}: {got} vs {want}"


def test_grover_zero_iterations_is_uniform():
    k = 3
    counts = _simulate(build_grover(k, registry.grover_pairs(k), iterations=0))
    assert len(counts) == 2**k
    assert all(abs(n / SHOTS - 1 / 2**k) < 0.03 for n in counts.values())


# ---- metadata, registry, scoring --------------------------------------------------------


@pytest.mark.parametrize("k", KS)
def test_grover_metadata_label_inputs_and_no_key(k):
    qc = registry.build_circuit(f"grover_present_k{k}")
    md = qc.metadata
    assert md["name"] == f"grover_present_k{k}"
    assert md["kind"] == "generic"
    assert md["key_bits"] == k
    # plan A (OPTIMIZE r1): 2 pairs for k <= 4, 3 for k = 5; M = 1 for every key is checked
    # separately (test_grover_registry_plaintexts_give_m_equal_one_for_every_key)
    assert len(md["pairs"]) == len(_registry_plaintexts(k)) == (3 if k == 5 else 2)
    assert md["iterations"] == default_iterations(k)
    assert not {"key", "keys", "secret", "k0", "k1", "consistent_keys"} & set(md)
    assert [(r.name, r.size) for r in qc.cregs] == [("key", k)]
    want = grover_success(len(consistent_keys(k, md["pairs"])), 2**k, md["iterations"])
    assert math.isclose(md["theoretical_success"], want, abs_tol=1e-6)


@pytest.mark.parametrize("k", KS)
def test_grover_registry_success_fn_accepts_only_the_consistent_key(k):
    pairs = registry.grover_pairs(k)
    good = set(consistent_keys(k, pairs))
    fn = registry.SUCCESS_FN[f"grover_present_k{k}"]
    for key in range(2**k):
        assert fn(format(key, f"0{k}b")) is (key in good)


@pytest.mark.parametrize("k", KS)
def test_grover_registry_theory_value_pinned(k):
    pinned = {2: 1.0, 3: 0.9453125, 4: 0.961319, 5: 0.999182}
    assert math.isclose(registry.THEORY_FN[f"grover_present_k{k}"](), pinned[k], abs_tol=1e-6)


@pytest.fixture(scope="module")
def grover_records(tmp_path_factory):
    out = tmp_path_factory.mktemp("grover_metrics")
    return {
        k: record_circuit_metrics(
            f"grover_present_k{k}", registry.build_circuit(f"grover_present_k{k}"), out_dir=out
        )
        for k in KS
    }, out


@pytest.mark.parametrize("k", KS)
def test_grover_metrics_record(grover_records, k):
    recs, out = grover_records
    rec = recs[k]
    assert rec["kind"] == "generic" and rec["shots"] >= 8192
    assert rec["success_probability"] >= rec["theoretical_success"] - 0.02
    assert abs(rec["success_probability"] - rec["theoretical_success"]) <= 0.02  # two-sided
    m = len(consistent_keys(k, registry.grover_pairs(k)))
    assert math.isclose(rec["chance_baseline"], grover_chance_baseline(m, k), abs_tol=1e-9)
    assert rec["success_probability"] > rec["chance_baseline"]  # theory is above chance here
    assert rec["two_qubit_gates"] > 0 and rec["transpile"]["backend"] == "fake_kingston"
    assert json.loads((out / f"grover_present_k{k}.json").read_text()) == rec


def test_grover_metrics_two_qubit_count_grows_with_key_size(grover_records):
    counts = [grover_records[0][k]["two_qubit_gates"] for k in KS]
    assert counts == sorted(counts) and len(set(counts)) == 4


# ---- leak tests -------------------------------------------------------------------------


def test_leak_grover_builder_signatures_take_no_key():
    for fn in (build_grover, build_oracle):
        names = set(inspect.signature(fn).parameters)
        assert not names & {"key", "keys", "secret", "k0", "k1", "answer", "target"}, names
    assert list(inspect.signature(build_grover).parameters)[:2] == ["key_bits", "pairs"]


def test_leak_grover_source_never_calls_the_cipher_or_brute_force():
    tree = ast.parse(inspect.getsource(grover_present))
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imported = {
        a.name.split(".")[-1]
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in n.names
    } | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    forbidden = {
        "encrypt", "consistent_keys", "grover_key_ok", "GROVER_DEMO_KEYS", "classical_order",
    }  # fmt: skip
    assert not (used | imported) & forbidden, (used | imported) & forbidden
    assert not any("registry" in str(m) for m in imported)


def test_leak_grover_source_has_no_loop_over_the_key_space():
    tree = ast.parse(inspect.getsource(grover_present))
    for loop in (n for n in ast.walk(tree) if isinstance(n, ast.For)):
        for node in ast.walk(loop.iter):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
                pytest.fail(f"loop over 2**x at line {loop.lineno}")


@pytest.mark.parametrize("k", KS)
def test_leak_grover_same_builder_finds_other_random_keys(k):
    rng = random.Random(1000 + k)
    demo = registry.GROVER_DEMO_KEYS[k]
    others = [x for x in range(2**k) if x != demo]
    for key in rng.sample(others, min(3, len(others))):
        pairs = make_pairs(key, DEMO_PT)
        marked = set(consistent_keys(k, pairs))
        assert marked == {key}
        qc = build_grover(k, pairs)
        counts = _simulate(qc, seed=k * 100 + key)
        theory = grover_success(1, 2**k, qc.metadata["iterations"])
        assert _mass_on(counts, marked) >= theory - 0.03, f"k={k} key={key}"
        assert max(counts, key=counts.get) == format(key, f"0{k}b")


@pytest.mark.parametrize("k", [3, 4])
def test_leak_grover_same_builder_other_plaintext_sets(k):
    rng = random.Random(77 + k)
    for _ in range(2):
        key = rng.randrange(2**k)
        pts = tuple(rng.sample(range(16), 3))
        pairs = make_pairs(key, pts)
        marked = set(consistent_keys(k, pairs))
        qc = build_grover(k, pairs)  # iterations assume M = 1, like a real attacker
        theory = grover_success(len(marked), 2**k, qc.metadata["iterations"])
        counts = _simulate(qc)
        assert _mass_on(counts, marked) >= theory - 0.03, f"k={k} pts={pts} M={len(marked)}"


def test_leak_grover_circuit_depends_on_the_ciphertexts():
    # same plaintexts, different keys -> different circuits (the answer enters only via pairs)
    a = build_grover(4, make_pairs(3, DEMO_PT))
    b = build_grover(4, make_pairs(12, DEMO_PT))
    assert a.metadata["pairs"] != b.metadata["pairs"]
    assert [i.operation.name for i in a.data] != [i.operation.name for i in b.data] or any(
        ia.qubits != ib.qubits for ia, ib in zip(a.data, b.data, strict=False)
    )


# ---- the registry's own plaintext choice must pin the key for EVERY key (M = 1) -------------


def _registry_plaintexts(k):
    pts = registry.GROVER_PLAINTEXTS
    return tuple(pts[k]) if isinstance(pts, dict) else tuple(pts)


@pytest.mark.parametrize("k", KS)
def test_grover_registry_plaintexts_give_m_equal_one_for_every_key(k):
    # if the demo uses fewer pairs, success ("any consistent key") would stop meaning "the true
    # key" and the M = 1 iteration count would be wrong: check all keys, not only the demo key
    pts = _registry_plaintexts(k)
    for key in range(2**k):
        assert consistent_keys(k, make_pairs(key, pts)) == [key], f"k={k} key={key} pts={pts}"


@pytest.mark.parametrize("k", KS)
def test_grover_registry_pairs_come_from_the_registry_plaintexts(k):
    pairs = registry.grover_pairs(k)
    assert tuple(p for p, _ in pairs) == _registry_plaintexts(k)
    assert registry.build_circuit(f"grover_present_k{k}").metadata["pairs"] == pairs


@pytest.mark.parametrize("k", KS)
def test_leak_grover_gate_structure_is_the_same_for_every_key(k):
    # the key enters only through the X gates that set the ciphertext target
    def skeleton(key):
        qc = build_grover(k, make_pairs(key, _registry_plaintexts(k)))
        return sorted((i.operation.name, len(i.qubits)) for i in qc.data if i.operation.name != "x")

    ref = skeleton(0)
    assert all(skeleton(key) == ref for key in range(1, 2**k))


@pytest.mark.parametrize("k", [2, 3, 4])
def test_grover_transpiled_circuit_matches_theory(k):
    # metrics.py never simulates the transpiled circuit it counts gates for; do it here
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    from quantum.backends import get_fake_backend

    qc = registry.build_circuit(f"grover_present_k{k}")
    tqc = generate_preset_pass_manager(
        optimization_level=3, backend=get_fake_backend(), seed_transpiler=1234
    ).run(qc)
    counts = AerSimulator(seed_simulator=99).run(tqc, shots=SHOTS).result().get_counts()
    got = _mass_on(counts, set(consistent_keys(k, qc.metadata["pairs"])))
    assert abs(got - qc.metadata["theoretical_success"]) < 0.03


def test_grover_chance_baselines_pinned():
    assert [grover_chance_baseline(1, k) for k in KS] == [0.25, 0.125, 0.0625, 0.03125]


@pytest.mark.parametrize("k", KS)
def test_grover_registry_rejects_builder_metadata_that_disagrees(k):
    name = f"grover_present_k{k}"
    good = dict(registry.build_circuit(name).metadata)
    registry._check_metadata(name, good)
    for key, bad in [("iterations", good["iterations"] + 1), ("key_bits", k + 1),
                     ("pairs", good["pairs"][:-1])]:  # fmt: skip
        with pytest.raises(ValueError):
            registry._check_metadata(name, {**good, key: bad})


@pytest.mark.parametrize("k", KS)
def test_grover_circuit_metadata_carries_the_independent_chance_baseline(k):
    md = registry.build_circuit(f"grover_present_k{k}").metadata
    m = len(consistent_keys(k, md["pairs"]))
    assert m == 1
    assert math.isclose(md["chance_baseline"], grover_chance_baseline(m, k), abs_tol=1e-9)
