import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

test('choosing dark persists across a reload', async ({ page }) => {
  await withDisplay(page, {});
  await gotoStable(page, '/fr/settings');

  await page.getByRole('radio', { name: /sombre|dark|dunkel/i }).first().click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

  await page.reload();
  // The blocking script in <head> must restore this before first paint; if it
  // ran in an effect instead, this assertion would still pass but the user
  // would see a flash of light.
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

test('high contrast composes with dark rather than replacing it', async ({ page }) => {
  await withDisplay(page, { theme: 'dark' });
  await gotoStable(page, '/fr/settings');

  await page.getByRole('switch', { name: /contraste|contrast|kontrast/i }).first().click();
  await expect(page.locator('html')).toHaveAttribute('data-contrast', 'high');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

test('the keyboard alone can reach and operate the settings', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'phone', 'keyboard flow is a desktop concern');
  await withDisplay(page, {});
  await gotoStable(page, '/fr/settings');

  await page.keyboard.press('Tab');
  const focused = await page.evaluate(() => document.activeElement?.tagName ?? '');
  expect(focused).not.toBe('BODY');

  // The focus ring is a design commitment, not a default: assert something is
  // actually painted around the focused element.
  const outline = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el) return '';
    const s = getComputedStyle(el);
    return `${s.boxShadow}|${s.outlineStyle}`;
  });
  expect(outline).not.toBe('none|none');
});
