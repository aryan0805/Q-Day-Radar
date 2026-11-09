# Phase 5 Lighthouse (mobile, local, median of 3)

Measured 2026-11-09T01:24:34Z. Lighthouse mobile defaults, performance+accessibility, --headless=new, local static server, median of 3 (the gate's invocation); lab data.
Thresholds: performance >= 0.9, accessibility = 1.0, LCP < 2000 ms, CLS < 0.05.

| build | screen | performance | accessibility | LCP | CLS | TBT | meets thresholds |
| --- | --- | ---: | ---: | ---: | ---: | ---: | :---: |
| pre-8c-dc77fde | / | 1.00 | 1.00 | 901 ms | 0.000 | 11 ms | yes |
| pre-8c-dc77fde | /lab/ | 1.00 | 1.00 | 902 ms | 0.036 | 1 ms | yes |
| pre-8c-dc77fde | /scaling/ | 1.00 | 1.00 | 902 ms | 0.000 | 0 ms | yes |
| pre-8c-dc77fde | /inventory/ | 1.00 | 1.00 | 1051 ms | 0.002 | 0 ms | yes |
| final-head | / | 1.00 | 1.00 | 901 ms | 0.000 | 0 ms | yes |
| final-head | /lab/ | 1.00 | 1.00 | 1051 ms | 0.003 | 1 ms | yes |
| final-head | /scaling/ | 1.00 | 1.00 | 901 ms | 0.001 | 0 ms | yes |
| final-head | /inventory/ | 1.00 | 1.00 | 1201 ms | 0.005 | 0 ms | yes |
