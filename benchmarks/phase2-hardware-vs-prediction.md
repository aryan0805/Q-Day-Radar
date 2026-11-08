# Phase 2 hardware vs pre-registered prediction (batch-20261108T044751Z, ibm_kingston)

4096 shots per job, 2 repeats per static config (1 for shor15_beauregard); transpile seed 1234; predictions are Aer simulations of the same ISA with the live Kingston calibration (seed 1234). Success next to its chance baseline; normalized = (s-c)/(t-c).

| circuit | config | repeats | pooled | Wilson 95% | chance | theory | normalized | predicted | obs-pred | lo>chance |
|---|---|---|---|---|---|---|---|---|---|---|
| shor15_beauregard | raw | 0.1750 | 0.1750 | [0.1637, 0.1870] | 0.1719 | 0.5000 | +0.010 | 0.1755 | -0.0005 | no |
| shor15_textbook | raw | 0.3765 / 0.3386 | 0.3575 | [0.3472, 0.3680] | 0.1719 | 0.5000 | +0.566 | 0.4287 | -0.0712 | yes |
| shor15_textbook | dd | 0.3760 / 0.3606 | 0.3683 | [0.3579, 0.3788] | 0.1719 | 0.5000 | +0.599 | 0.4287 | -0.0604 | yes |
| shor15_textbook | dd_twirl | 0.3694 / 0.3691 | 0.3693 | [0.3589, 0.3798] | 0.1719 | 0.5000 | +0.602 | 0.4287 | -0.0594 | yes |
| grover_present_k2 | raw | 0.4651 / 0.5452 | 0.5051 | [0.4943, 0.5159] | 0.2500 | 1.0000 | +0.340 | 0.6511 | -0.1460 | yes |
| grover_present_k2 | dd | 0.4868 / 0.4915 | 0.4891 | [0.4783, 0.5000] | 0.2500 | 1.0000 | +0.319 | 0.6511 | -0.1620 | yes |
| grover_present_k2 | dd_twirl | 0.4832 / 0.4814 | 0.4823 | [0.4715, 0.4931] | 0.2500 | 1.0000 | +0.310 | 0.6511 | -0.1688 | yes |
| grover_present_k3 | raw | 0.1443 / 0.1494 | 0.1469 | [0.1394, 0.1547] | 0.1250 | 0.9453 | +0.027 | 0.3413 | -0.1945 | yes |
| grover_present_k3 | dd | 0.1411 / 0.1404 | 0.1407 | [0.1334, 0.1484] | 0.1250 | 0.9453 | +0.019 | 0.3413 | -0.2006 | yes |
| grover_present_k3 | dd_twirl | 0.1497 / 0.1538 | 0.1517 | [0.1441, 0.1597] | 0.1250 | 0.9453 | +0.033 | 0.3413 | -0.1896 | yes |
| grover_present_k4 | raw | 0.0557 / 0.0518 | 0.0537 | [0.0490, 0.0588] | 0.0625 | 0.9613 | -0.010 | 0.1416 | -0.0879 | no |
| grover_present_k4 | dd | 0.0767 / 0.0769 | 0.0768 | [0.0712, 0.0827] | 0.0625 | 0.9613 | +0.016 | 0.1416 | -0.0648 | yes |
| grover_present_k4 | dd_twirl | 0.0652 / 0.0688 | 0.0670 | [0.0618, 0.0726] | 0.0625 | 0.9613 | +0.005 | 0.1416 | -0.0746 | no |
| grover_present_k5 | raw | 0.0273 / 0.0281 | 0.0277 | [0.0244, 0.0315] | 0.0312 | 0.9992 | -0.004 | 0.0476 | -0.0199 | no |
| grover_present_k5 | dd | 0.0349 / 0.0359 | 0.0354 | [0.0316, 0.0396] | 0.0312 | 0.9992 | +0.004 | 0.0476 | -0.0122 | yes |
| grover_present_k5 | dd_twirl | 0.0291 / 0.0288 | 0.0289 | [0.0255, 0.0328] | 0.0312 | 0.9992 | -0.002 | 0.0476 | -0.0187 | no |
