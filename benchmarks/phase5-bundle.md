# Phase 5 bundle: JS fetched on the home page

Measured 2026-11-08T23:46:25Z in Chromium at 390 px. gzip -9 of each JS response body and executable inline script; network idle + 5 s with no interaction, then one wheel scroll. Budget: 200,000 B before the first interaction.

| build | mode | static (index.html) | before interaction | GSAP before | after one scroll | added by scroll | GSAP chunk | within budget |
| --- | --- | ---: | ---: | :---: | ---: | ---: | ---: | :---: |
| before-dc77fde | normal motion | 193,188 B | 249,789 B | yes | 249,789 B | +0 B | 27,327 B | NO |
| before-dc77fde | reduced motion | 193,188 B | 205,020 B | no | 205,020 B | +0 B | 0 B | NO |
| after-a7f5ec9 | normal motion | 194,546 B | 188,831 B | no | 251,310 B | +62,479 B | 27,327 B | yes |
| after-a7f5ec9 | reduced motion | 194,546 B | 198,072 B | no | 206,541 B | +8,469 B | 0 B | yes |

Other-origin requests (all builds, both modes): []
