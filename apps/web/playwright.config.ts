import { defineConfig, devices } from '@playwright/test';

/**
 * Two viewports, because the product is genuinely used on both: a laptop at a
 * desk and a phone in the classroom (photographing copies is a phone workflow).
 * A desktop-only suite would never catch the matrix pushing the page sideways.
 */
const PORT = 3100;
const baseURL = `http://127.0.0.1:${PORT}`;

/**
 * CI installs Playwright's own pinned Chromium, which is what the screenshot
 * baselines are rendered against. Set PLAYWRIGHT_CHANNEL=chrome to run against
 * a locally installed Chrome instead — useful where the pinned build cannot be
 * downloaded. Screenshots will differ slightly; run the behavioural specs with
 * `--grep-invert "renders in"` when using it.
 */
const channel = process.env.PLAYWRIGHT_CHANNEL;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  timeout: 30_000,
  expect: {
    // Font rasterisation differs slightly between machines; a tiny tolerance
    // keeps the suite meaningful instead of permanently red.
    toHaveScreenshot: { maxDiffPixelRatio: 0.02, animations: 'disabled' },
  },
  use: {
    baseURL,
    trace: 'on-first-retry',
    // Deterministic screenshots: no live clock, no live data.
    timezoneId: 'Europe/Zurich',
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, ...(channel ? { channel } : {}) },
    },
    {
      name: 'phone',
      use: { ...devices['Pixel 7'], viewport: { width: 390, height: 844 }, ...(channel ? { channel } : {}) },
    },
  ],
  webServer: {
    // A production build, not `next dev`. The dev server compiles routes on
    // demand, so the first visit to each page is slow and the suite goes flaky
    // the moment it runs in parallel -- and a screenshot taken mid-compile is
    // worse than no screenshot. The fixture layer answers every request, so
    // this needs no API, no database and no API key.
    command: `NEXT_PUBLIC_ALPPY_MOCK=1 pnpm exec next build && NEXT_PUBLIC_ALPPY_MOCK=1 pnpm exec next start -p ${PORT}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
  },
});
