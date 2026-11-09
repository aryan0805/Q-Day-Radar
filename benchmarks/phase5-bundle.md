# Phase 5 bundle: JS fetched on the home page

Measured 2026-11-09T01:47:47Z in Chromium at 390 px. gzip -9 of each JS response body and executable inline script; network idle + 5 s with no interaction, then one wheel scroll. Budget: 200,000 B before the first interaction.

| build | mode | static (index.html) | before interaction | GSAP before | after one scroll | added by scroll | GSAP chunk | within budget |
| --- | --- | ---: | ---: | :---: | ---: | ---: | ---: | :---: |
| before-dc77fde | normal motion | 193,188 B | 249,789 B | yes | 249,789 B | +0 B | 27,327 B | NO |
| before-dc77fde | reduced motion | 193,188 B | 205,020 B | no | 205,020 B | +0 B | 0 B | NO |
| final-head | normal motion | 194,755 B | 189,958 B | no | 249,387 B | +59,429 B | 27,327 B | yes |
| final-head | reduced motion | 194,755 B | 196,100 B | no | 204,618 B | +8,518 B | 0 B | yes |

Other-origin requests (all builds, both modes): []
