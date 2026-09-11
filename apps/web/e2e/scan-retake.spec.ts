import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * A page that would not register has a route back into its own pile (F11).
 *
 * Before this, an unregistered page carried two sentences of advice — "reprenez
 * la photo en cadrant les quatre coins" — and a Discard button, and there was
 * nowhere to act on the advice. The only path was `/scans/new`, which creates a
 * SECOND pile against the same sheet: a second review, a second confirmation,
 * and one class's submission split across two records with nothing saying they
 * belong together. The likelier alternative was worse — discard the three bad
 * photographs, confirm the twenty-seven, and three pupils are silently
 * unassessed on that sheet.
 */
const SCAN_ID = '00000000-0000-4000-8000-000000000800';

test.describe('retaking a page', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('an unregistered page offers a retake, into this pile', async ({ page }) => {
    await gotoStable(page, `/fr/scans/${SCAN_ID}`);

    // The advice, and now something to do about it.
    await expect(page.getByText(/reprenez la photo/i)).toBeVisible();
    await expect(page.getByText(/reprendre cette page/i)).toBeVisible();
    await expect(page.getByText(/remplace celle-ci dans la même pile/i)).toBeVisible();
  });

  test('the retake goes to this scan rather than creating a second pile', async ({ page }) => {
    await gotoStable(page, `/fr/scans/${SCAN_ID}`);

    const input = page.locator('input[type="file"]').first();
    await input.setInputFiles({
      name: 'retake.png',
      mimeType: 'image/png',
      // A one-pixel PNG: the fixture never decodes it, and what is under test
      // is which endpoint the click reaches.
      buffer: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
        'base64',
      ),
    });

    await expect
      .poll(async () => {
        const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
        return calls.some((c) => c === `POST /scans/${SCAN_ID}/pages`);
      })
      .toBe(true);

    // The thing that must NOT happen: a new pile.
    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls, 'a retake must never create a second scan').not.toContain('POST /scans');
  });
});
