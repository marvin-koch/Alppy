import { expect, test } from '@playwright/test';

import { LOCALES, gotoStable, shot, withDisplay } from './helpers';

/**
 * French is the default. All three ship from day one, so all three are
 * screenshot — German is the one that catches layout breakage, because German
 * compound nouns are long and will overflow a box that French fits.
 */
for (const locale of LOCALES) {
  test(`home renders in ${locale}`, async ({ page }) => {
    await withDisplay(page, { theme: 'light' });
    await gotoStable(page, `/${locale}`);
    await expect(page.locator('html')).toHaveAttribute('lang', locale);
    await expect(page).toHaveScreenshot(shot('home-locale', locale), { fullPage: true });
  });

  test(`matrix renders in ${locale}`, async ({ page }) => {
    await withDisplay(page, { theme: 'light' });
    await gotoStable(page, `/${locale}/classes`);
    await expect(page).toHaveScreenshot(shot('classes-locale', locale), { fullPage: true });
  });
}

test('no untranslated key leaks into the page', async ({ page }) => {
  // next-intl falls back to the raw key when one is missing, so a dotted
  // identifier in the rendered text means a catalogue gap that the sync check
  // cannot see (it compares keys, not usage).
  for (const locale of LOCALES) {
    await withDisplay(page, { theme: 'light' });
    await gotoStable(page, `/${locale}`);
    const text = await page.locator('main').innerText();
    expect(text, `${locale} shows a raw message key`).not.toMatch(
      /\b(home|nav|common|mastery|sheets|scans|adaptive)\.[a-zA-Z]+\.[a-zA-Z]+\b/,
    );
  }
});

test('the locale switch persists across a reload', async ({ page }) => {
  await withDisplay(page, { theme: 'light' });
  await gotoStable(page, '/de');
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
});
