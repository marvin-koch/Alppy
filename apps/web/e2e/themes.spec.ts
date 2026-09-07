import { expect, test } from '@playwright/test';

import { gotoMatrix, gotoStable, shot, withDisplay, type Display } from './helpers';

/**
 * DESIGN.md §8: three theme states, not two, plus an independent contrast layer
 * and a calm layer. They compose, and `data-theme="dark" data-contrast="high"`
 * is explicitly a valid, tested state — so it is tested here.
 */
const COMBINATIONS: Array<{ name: string; display: Display }> = [
  { name: 'system', display: {} },
  { name: 'light', display: { theme: 'light' } },
  { name: 'dark', display: { theme: 'dark' } },
  { name: 'contrast', display: { contrast: 'high' } },
  { name: 'dark-contrast', display: { theme: 'dark', contrast: 'high' } },
  { name: 'calm', display: { calm: 'on' } },
];

for (const { name, display } of COMBINATIONS) {
  test(`home renders in ${name}`, async ({ page }) => {
    await withDisplay(page, display);
    await gotoStable(page, '/fr');
    await expect(page).toHaveScreenshot(shot('home', name), { fullPage: true });
  });

  test(`matrix renders in ${name}`, async ({ page }) => {
    await withDisplay(page, display);
    await gotoMatrix(page, 'fr');
    await expect(page).toHaveScreenshot(shot('classes', name), { fullPage: true });
  });
}

test('an explicit light choice beats a dark system preference', async ({ page }) => {
  // This is the case the `:not([data-theme="light"])` selector exists for, and
  // it is invisible to a test that only checks the two explicit themes.
  await page.emulateMedia({ colorScheme: 'dark' });
  await withDisplay(page, { theme: 'light' });
  await gotoStable(page, '/fr');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  // The light canvas is #F7F5FF; the dark one is much darker. Compare luminance
  // rather than an exact string, which varies by browser.
  const [r, g, b] = bg.match(/\d+/g)!.map(Number);
  expect((r! + g! + b!) / 3).toBeGreaterThan(200);
});

test('calm mode removes decorative illustrations', async ({ page }) => {
  await withDisplay(page, { calm: 'on' });
  await gotoStable(page, '/fr/sources');
  const decorative = page.locator('[data-decorative]');
  const count = await decorative.count();
  for (let i = 0; i < count; i += 1) {
    await expect(decorative.nth(i)).toBeHidden();
  }
});
