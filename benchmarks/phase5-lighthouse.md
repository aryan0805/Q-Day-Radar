# Phase 5 Lighthouse (mobile, local, median of 3)

Measured 2026-11-08T23:41:07Z. Lighthouse mobile defaults, performance+accessibility, --headless=new, local static server, median of 3 (the gate's invocation); lab data.
Thresholds: performance >= 0.9, accessibility = 1.0, LCP < 2000 ms, CLS < 0.05.

| build | screen | performance | accessibility | LCP | CLS | TBT | meets thresholds |
| --- | --- | ---: | ---: | ---: | ---: | ---: | :---: |
| pre-8c-dc77fde | / | 1.00 | 1.00 | 901 ms | 0.000 | 12 ms | yes |
| pre-8c-dc77fde | /lab/ | 1.00 | 1.00 | 901 ms | 0.036 | 2 ms | yes |
| pre-8c-dc77fde | /scaling/ | 1.00 | 1.00 | 901 ms | 0.000 | 1 ms | yes |
| pre-8c-dc77fde | /inventory/ | 1.00 | 1.00 | 1052 ms | 0.002 | 2 ms | yes |
| now-a7f5ec9 | / | 1.00 | 1.00 | 901 ms | 0.000 | 0 ms | yes |
| now-a7f5ec9 | /lab/ | 1.00 | 1.00 | 1051 ms | 0.003 | 2 ms | yes |
| now-a7f5ec9 | /scaling/ | 1.00 | 1.00 | 901 ms | 0.001 | 0 ms | yes |
| now-a7f5ec9 | /inventory/ | 1.00 | 1.00 | 1201 ms | 0.005 | 2 ms | yes |
