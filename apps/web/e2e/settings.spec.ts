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

test('a ghost button shows the focus ring like every other variant', async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'phone', 'the drawer trigger is the phone-only ghost');
  await withDisplay(page, {});
  await gotoStable(page, '/fr');

  const trigger = page.getByRole('button', { name: 'Ouvrir le menu' });
  await trigger.focus();
  // `.ard-btn[data-variant='ghost']`'s `box-shadow: none` had the same
  // specificity as `.ard-btn:focus-visible` and came later, so it won and the
  // ring was never drawn. The transition has to settle before measuring.
  await page.waitForTimeout(400);
  const shadow = await trigger.evaluate((el) => getComputedStyle(el).boxShadow);
  expect(shadow, 'ghost buttons must draw --focus-ring').toContain('rgb(91, 63, 240)');
});

test('the drawer is a modal, and gives focus back when it closes', async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'phone', 'the drawer is the phone layout');
  await withDisplay(page, {});
  await gotoStable(page, '/fr');

  const trigger = page.getByRole('button', { name: 'Ouvrir le menu' });
  await trigger.focus();
  await page.keyboard.press('Enter');

  const dialog = page.locator('[role=dialog]');
  await expect(dialog).toBeVisible();
  // Focus is genuinely trapped, so say so.
  await expect(dialog).toHaveAttribute('aria-modal', 'true');
  // ...and the region is named for what it is, not for the button that opened it.
  await expect(dialog).not.toHaveAccessibleName('Ouvrir le menu');

  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  // Radix focused a null trigger ref and cancelled its own fallback, so focus
  // landed on <body> and a keyboard user restarted from the top of the page.
  await expect(trigger).toBeFocused();
});
