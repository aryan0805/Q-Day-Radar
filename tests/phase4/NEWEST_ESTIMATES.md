# Newest published Shor estimates, searched independently of builder (reviewer, 2026-11-08)

Purpose: the fairness rule (each Shor target is compared with its most recent estimate) must not
be decided by whichever paper builder happened to find. Search done by a `fact-checker` subagent
and re-checked by the reviewer where marked. This file is NOT a data source: only verified entries
in `quantum/estimate/literature.yaml` feed the model.

Status key: **P** = reviewer re-read the primary text (abstract/first page of the PDF);
**A** = read by the subagent in the primary PDF, not re-read; **S** = secondary source only (do not use).

| Date | Paper | Target | Physical qubits | Runtime | Assumptions (as the paper states them) | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-28 | Alice & Bob, ePrint 2026/2665 | ECC-256 (secp256k1), RSA-2048 | "at most 30 000 cat qubits" (ECC, abstract) | "1 hour" (abstract) | cat qubits, 1 us cycle, 10 us reaction, phase-flip noise only (p_Z 5e-4 per abstract; one secondary says 1e-3) | abstract only (PDF 403): exact figures **S** |
| 2026-09-04 | IonQ, Haner et al., arXiv 2609.05625 | ECC-256 | 19,397 (abstract) | about 25.7 days (abstract) | trapped-ion Walking Cat, qLDPC, 2q noise 1e-4, 5.4 ms syndrome cycle | **P** (abstract), tables **A** |
| 2026-03-30 | Google QAI, Babbush et al., arXiv 2603.28846 v2 | ECC-256 | only "fewer than half a million" (a bound, no exact count) | "minutes" (abstract); 18 or 23 min (Sec. II.B, **A**) | superconducting, surface code variants, planar, p = 1e-3, 10 us reaction | **P** (abstract) |
| 2026-03-30 | Cain et al., arXiv 2603.28627 | ECC-256, RSA-2048 | 9,739 to about 26,000 depending on variant | about 1000 d to about 10 d | neutral atoms, qLDPC, 1 ms cycle, non-local connectivity | **A** |
| 2026-02-12 | Webster et al. (Iceberg), arXiv 2602.11457 | RSA-2048 only | under 100,000 (abstract) | per Table VI | p = 1e-3, 1 us, 10 us reaction, qLDPC, non-local | **A** |
| 2023 | Litinski, arXiv 2306.08585 | ECC-256 | the ~9.4e6 already in literature.yaml | | | cited by IonQ p.4 (**A**) |
| 2025-05-21 | Gidney, arXiv 2505.15917 | RSA-2048 | under one million | under a week | p = 1e-3, 1 us surface-code cycle | already in literature.yaml |

## What this changes

1. **Litinski 2023 is not the newest ECC-256 estimate.** At least four later papers exist. A
   RSA(2025) vs ECC(2023) comparison is lopsided by recency, exactly the worry in the brief.
2. **Only one newer ECC paper is on a scenario's hardware family** (surface code, p = 1e-3,
   microsecond rounds, planar): Google 2026. It gives a **bound** ("fewer than half a million"),
   not a point estimate, so it must be stored and labelled as an upper bound, with its runtime.
3. The others (IonQ ions at 1e-4, Cain atoms at a 1 ms cycle, Alice & Bob cat qubits) use other
   hardware; by the brief's rule they cannot replace a scenario's model numbers. They may be shown
   as literature context, labelled with their own assumptions.
4. Newest-to-newest, ECC-256 (Google 2026, a bound under 500k) is not above RSA-2048 (Gidney 2025,
   under 1M): the Phase 3 order "RSA cheaper" came from comparing our model with a 2023 paper.
   The order in the inventory must be computed after the fairness rule is applied, and AUDIT.md says so.

## Not found / not verified

No exact physical-qubit count in the Google paper (reviewer did not read beyond the abstract page;
the subagent read pp.1-10). The Alice & Bob PDF could not be opened. Litinski 2023 and Gouzien 2023
(126,133 cat qubits, 9 h; a repetition cat code) were not re-read this round.
