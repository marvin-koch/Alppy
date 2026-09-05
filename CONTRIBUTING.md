
## Screenshot baselines

The theme, contrast, calm and locale screenshots are compared per platform:
Playwright files them as `…-darwin.png`, `…-linux.png` and so on, because font
rasterisation differs enough between operating systems that a macOS baseline
will never match a Linux runner.

The committed baselines were generated on macOS. To make screenshot regression
enforcing in CI, generate the Linux set once in the same image CI uses and
commit them:

```bash
docker run --rm -v "$PWD":/w -w /w mcr.microsoft.com/playwright:v1.63.0-noble \
  sh -c "corepack enable pnpm && pnpm install --frozen-lockfile && \
         pnpm --filter @alppy/web exec playwright test --grep 'renders in' --update-snapshots"
```

Then flip the `Run Playwright (screenshots)` step in `.github/workflows/ci.yml`
from `continue-on-error: true` to enforcing. Until that is done, the behavioural
specs are the ones actually gating a merge.

Locally, if Playwright's pinned Chromium will not download, run against an
installed Chrome instead:

```bash
PLAYWRIGHT_CHANNEL=chrome pnpm --filter @alppy/web exec playwright test --grep-invert "renders in"
```

Screenshots will not match under that flag — it is for the behavioural specs.
