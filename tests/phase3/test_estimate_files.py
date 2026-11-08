"""Per-case estimate files: schema, the toffoli_equiv formula, and P005 base rules.

These read what the estimators wrote and recompute everything that can be recomputed from
the raw counts with reference.py, so a wrong count or a wrong conversion fails here.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import subprocess

import pytest

from tests.phase3 import reference as ref

QDK_KEYS = {
    "case",
    "kind",
    "N",
    "n_bits",
    "base_a",
    "logical_counts",
    "toffoli_equiv",
    "rotation_eps",
    "rotation_t_cost",
    "tool",
}
QDK_COUNTS = {
    "num_qubits",
    "t_count",
    "rotation_count",
    "ccz_count",
    "ccix_count",
    "measurement_count",
}
QT_KEYS = {
    "case",
    "method",
    "bloq",
    "N",
    "n_bits",
    "base_a",
    "logical_qubits",
    "counts",
    "toffoli_equiv",
    "rotation_eps",
    "rotation_t_cost",
    "tool",
}
QT_COUNTS = {"toffoli", "t", "rotations"}
SCALING = re.compile(r"^beauregard_N(\d+)_a(\d+)$")
MODEXP = re.compile(r"^modexp_N(\d+)_a(\d+)$")


def test_estimate_env_matches_installed_versions():
    env = ref.load_json(ref.EST / "env.json")
    for pkg in ("qsharp", "qualtran"):
        assert env.get(pkg) == md.version(pkg), f"env.json {pkg}={env.get(pkg)!r}"
    assert str(env.get("qiskit", "")).startswith("2."), env.get("qiskit")
    assert env.get("python")


@pytest.mark.parametrize("tool", ["qdk", "qualtran"])
def test_estimate_schema_every_file(tool):
    keys, counts_key = (QDK_KEYS, "logical_counts") if tool == "qdk" else (QT_KEYS, "counts")
    want_counts = QDK_COUNTS if tool == "qdk" else QT_COUNTS
    for case, c in ref.cases(tool).items():
        assert keys <= set(c), f"{tool}/{case}: missing {sorted(keys - set(c))}"
        assert c["case"] == case, f"{tool}/{case}: case field is {c['case']!r}"
        assert c["tool"]["name"] == ("qsharp" if tool == "qdk" else "qualtran")
        assert c["tool"]["version"] == md.version(c["tool"]["name"]), f"{tool}/{case} version"
        counts = c[counts_key]
        assert want_counts <= set(counts), f"{tool}/{case}: counts miss {want_counts - set(counts)}"
        for k in want_counts:
            assert counts[k] >= 0 and float(counts[k]).is_integer(), (
                f"{tool}/{case}: {k}={counts[k]}"
            )
        assert (c["logical_counts"]["num_qubits"] if tool == "qdk" else c["logical_qubits"]) > 0


@pytest.mark.parametrize("tool", ["qdk", "qualtran"])
def test_estimate_toffoli_equiv_matches_formula_on_raw_counts(tool):
    """toffoli + ccz + ccix + t/4 + rotations * rotation_t_cost/4, one eps and cost everywhere."""
    seen = set()
    for case, c in ref.cases(tool).items():
        want = ref.equiv_of(tool, c)
        assert c["toffoli_equiv"] == pytest.approx(want, rel=1e-9), f"{tool}/{case}"
        seen.add((c["rotation_eps"], c["rotation_t_cost"]))
        assert 0 < c["rotation_eps"] < 1 and c["rotation_t_cost"] > 0
    assert len(seen) == 1, f"{tool}: several (eps, rotation_t_cost) pairs {seen}"


def test_estimate_both_tools_share_one_rotation_synthesis_cost():
    pairs = {
        (c["rotation_eps"], c["rotation_t_cost"])
        for t in ("qdk", "qualtran")
        for c in ref.cases(t).values()
    }
    assert len(pairs) == 1, f"tools disagree on rotation eps/cost: {pairs}"


def test_estimate_registry_circuits_all_present_with_right_kind():
    qdk = ref.cases("qdk")
    for name, kind in ref.REGISTRY.items():
        assert name in qdk, f"no QDK file for registry circuit {name}"
        assert qdk[name]["kind"] == kind, (
            f"{name}: kind {qdk[name]['kind']!r}, registry says {kind}"
        )
        assert qdk[name]["toffoli_equiv"] > 0, f"{name}: zero cost"


def test_estimate_every_shor_case_states_its_base_and_it_is_coprime():
    for tool in ("qdk", "qualtran"):
        for case, c in ref.cases(tool).items():
            if case.startswith(("shor", "beauregard", "modexp", "rsa2048")):
                assert c.get("base_a") is not None or case == "rsa2048_modexp", (
                    f"{tool}/{case}: no base_a"
                )
            if SCALING.match(case) or MODEXP.match(case):
                assert ref.order(c["base_a"], c["N"]) >= 1, f"{tool}/{case}: base not coprime"


def test_estimate_scaling_case_ids_agree_with_their_own_fields():
    for tool, rx in (("qdk", SCALING), ("qualtran", MODEXP)):
        for case, c in ref.cases(tool).items():
            m = rx.match(case)
            if not m:
                continue
            assert (c["N"], c["base_a"]) == (int(m[1]), int(m[2])), f"{tool}/{case}: id vs fields"
            assert c["n_bits"] == c["N"].bit_length(), f"{tool}/{case}: n_bits {c['n_bits']}"


def test_estimate_scaling_family_is_generic_and_N_is_two_distinct_odd_primes():
    fam = {k: v for k, v in ref.cases("qdk").items() if SCALING.match(k)}
    assert fam, "no beauregard_N<N>_a<a> files"
    for case, c in fam.items():
        assert c["kind"] == "generic", (
            f"{case} presented as {c['kind']}; only the generic builder is used"
        )
        f = ref.prime_factors(c["N"])
        assert len(f) == 2 and f[0] != f[1] and f[0] % 2 == 1, f"{case}: N={c['N']} factors {f}"


def test_estimate_P005_each_size_has_three_bases_and_not_only_order_two():
    sizes: dict[int, dict[int, dict]] = {}
    for case, c in ref.cases("qdk").items():
        if SCALING.match(case):
            sizes.setdefault(c["N"], {})[c["base_a"]] = c
    assert len(sizes) >= 5, f"{len(sizes)} sizes, need 5"
    assert len({v[next(iter(v))]["n_bits"] for v in sizes.values()}) >= 5, "sizes share bit lengths"
    for n, by_base in sorted(sizes.items()):
        assert len(by_base) >= 3, f"N={n}: bases {sorted(by_base)}"
        orders = {a: ref.order(a, n) for a in by_base}
        assert any(r > 2 for r in orders.values()), f"N={n}: orders {orders} are all <= 2"


def test_estimate_cost_grows_with_size_for_both_tools():
    """A wrong or truncated count shows up as a size that costs no more than a smaller one."""
    for tool, rx in (("qdk", SCALING), ("qualtran", MODEXP)):
        med: dict[int, list[float]] = {}
        qub: dict[int, list[int]] = {}
        for case, c in ref.cases(tool).items():
            if rx.match(case):
                med.setdefault(c["n_bits"], []).append(c["toffoli_equiv"])
                qub.setdefault(c["n_bits"], []).append(ref.qubits_of(tool, c))
        bits = sorted(med)
        assert len(bits) >= 4, f"{tool}: only sizes {bits}"
        import statistics

        meds = [statistics.median(med[b]) for b in bits]
        assert meds == sorted(meds) and len(set(meds)) == len(meds), (
            f"{tool}: {dict(zip(bits, meds, strict=False))}"
        )
        qmins = [min(qub[b]) for b in bits]
        assert qmins == sorted(qmins), f"{tool}: logical qubits shrink with size {qmins}"
        assert all(q >= b for q, b in zip(qmins, bits, strict=False)), (
            f"{tool}: fewer logical qubits than bits"
        )


def test_estimate_no_qpu_used_in_phase_3():
    for path in ("results/hardware", "results/budget.json"):
        r = subprocess.run(
            ["git", "diff", "--quiet", "phase-2-done", "--", path], cwd=ref.ROOT, check=False
        )
        assert r.returncode == 0, f"{path} changed since phase-2-done"


# ---- DECISIONS 2026-11-08 caveat C: Qualtran make_for_shor sizes x one bit short -----------
JUST_ABOVE_POWER_OF_TWO = (2**60 + 33, 2**126 + 15, 2**2046 + 9)


def test_estimate_upstream_qualtran_make_for_shor_undersizes_x_just_above_a_power_of_two():
    """Pins WHY we never call make_for_shor: x_bitsize = ceil(log2 N) in floats is one short.

    Reproduced on qualtran 0.7.0 only. On any other version this fails on purpose: re-run the
    reproduction, and if upstream is fixed, drop this pin (our own construction stays tested).
    """
    if md.version("qualtran") != "0.7.0":
        pytest.fail(f"qualtran {md.version('qualtran')}: re-run the caveat-C reproduction")
    from qualtran.bloqs.cryptography.rsa import ModExp

    for n in JUST_ABOVE_POWER_OF_TWO:
        bloq = ModExp.make_for_shor(n, g=3)
        assert bloq.x_bitsize == n.bit_length() - 1, f"{n.bit_length()} bits: x={bloq.x_bitsize}"


def test_estimate_qualtran_modexp_files_have_x_register_holding_N_and_2n_exponent_bits():
    """Every Qualtran bloq case stores n_bits == N.bit_length(), and the bloq is built from it."""
    bloq_cases = {k: v for k, v in ref.cases("qualtran").items() if v["method"] == "bloq"}
    assert bloq_cases, "no Qualtran bloq cases"
    for case, c in bloq_cases.items():
        if c["N"] is None:
            continue
        assert c["n_bits"] == int(c["N"]).bit_length(), f"{case}: n_bits {c['n_bits']}"
    rsa = ref.cases("qualtran").get("rsa2048_modexp")
    assert rsa is not None, "no rsa2048_modexp file"
    assert rsa["n_bits"] == 2048 and int(rsa["N"]).bit_length() == 2048, "RSA-2048 modulus size"


def assert_modexp_sizes(bloq, n_mod: int) -> None:
    """Shared check for a Qualtran ModExp: x register holds N, 2n exponent bits."""
    n = n_mod.bit_length()
    assert bloq.mod == n_mod
    assert bloq.x_bitsize == n, f"x_bitsize {bloq.x_bitsize}, N has {n} bits"
    assert bloq.exp_bitsize == 2 * n, f"exp_bitsize {bloq.exp_bitsize}, want {2 * n}"


def test_estimate_assert_modexp_sizes_rejects_the_upstream_bug_and_accepts_a_correct_bloq():
    from qualtran.bloqs.cryptography.rsa import ModExp

    n_mod = 2**60 + 33
    with pytest.raises(AssertionError):
        assert_modexp_sizes(ModExp.make_for_shor(n_mod, g=3), n_mod)
    good = ModExp(
        base=3, mod=n_mod, exp_bitsize=2 * n_mod.bit_length(), x_bitsize=n_mod.bit_length()
    )
    assert_modexp_sizes(good, n_mod)
