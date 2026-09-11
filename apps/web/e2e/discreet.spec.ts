import { expect, test } from '@playwright/test';

import { gotoStable, MATRIX_CLASS_ID, matrixPath, withDisplay } from './helpers';

/**
 * Projector mode (Phase 5).
 *
 * Alppy's screens get projected — the matrix goes up so the class can see what
 * the week looked like, the roster is left open while the room fills — and
 * every one of them put a pupil's name next to a band saying how that child is
 * doing. The product was careful in the other direction (no name reaches a
 * model provider) and had nothing for the audience actually in the room.
 *
 * These assert the thing that matters and cannot be assumed: that a name is
 * genuinely absent from the DOM, on each screen the audit names. Not hidden by
 * CSS — absent. A blur or an `opacity: 0` is a screenshot away from being
 * readable, and is still in the page for anyone who looks.
 */

/** From `lib/api/mock/fixtures.ts` — the first pupil of the demo class. */
const NAME = 'Chloé';
const UID = /7B_\d\d/;

async function project(page: import('@playwright/test').Page) {
  await withDisplay(page, {});
  // Set the way the settings screen sets it, so `ThemeScript` applies it
  // before paint exactly as it would for a teacher who chose it yesterday.
  await page.addInitScript(() => {
    const raw = window.localStorage.getItem('alppy.display');
    const prefs = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    window.localStorage.setItem('alppy.display', JSON.stringify({ ...prefs, discreet: 'on' }));
  });
}

test.describe('discreet mode', () => {
  test('the roster shows codes instead of names', async ({ page }) => {
    await project(page);
    await gotoStable(page, `/fr/classes/${MATRIX_CLASS_ID}/students`);

    await expect(page.getByText(NAME)).toHaveCount(0);
    await expect(page.getByText(UID).first()).toBeVisible();
  });

  test('the class matrix shows codes instead of names', async ({ page }) => {
    await project(page);
    await gotoStable(page, matrixPath('fr'));

    await expect(page.getByText(NAME)).toHaveCount(0);
    await expect(page.getByText(UID).first()).toBeVisible();
  });

  test('the results screen shows codes instead of names', async ({ page }) => {
    await project(page);
    await gotoStable(page, '/fr/results');

    await expect(page.getByText(NAME)).toHaveCount(0);
  });

  test('a pupil’s own profile shows the code too', async ({ page }) => {
    await project(page);
    await gotoStable(page, `/fr/classes/${MATRIX_CLASS_ID}/students`);
    await page.getByRole('link').filter({ hasText: UID }).first().click();
    await page.waitForLoadState('networkidle');

    await expect(page.getByText(NAME)).toHaveCount(0);
  });

  test('names come back only when the teacher asks, and not for long', async ({ page }) => {
    await project(page);
    await gotoStable(page, `/fr/classes/${MATRIX_CLASS_ID}/students`);

    await page.getByRole('button', { name: /afficher les noms/i }).click();
    await expect(page.getByText(NAME).first()).toBeVisible();
    // The screen keeps saying that names are showing — on a projector that is
    // the state a teacher most needs not to forget.
    await expect(page.getByText(/les noms sont visibles/i)).toBeVisible();

    // Leaving ends it. A reveal that survived a navigation would be a
    // projector mode that quietly turns itself off.
    await gotoStable(page, matrixPath('fr'));
    await expect(page.getByText(NAME)).toHaveCount(0);
  });

  test('without the preference, nothing changes and no control appears', async ({ page }) => {
    await withDisplay(page, {});
    await gotoStable(page, `/fr/classes/${MATRIX_CLASS_ID}/students`);

    await expect(page.getByText(NAME).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /afficher les noms/i })).toHaveCount(0);
  });

  test('the keyboard reaches it, because the projector is already on', async ({ page }) => {
    await withDisplay(page, {});
    await gotoStable(page, `/fr/classes/${MATRIX_CLASS_ID}/students`);
    await expect(page.getByText(NAME).first()).toBeVisible();

    await page.locator('#main').press('Shift+D');

    await expect(page.getByText(NAME)).toHaveCount(0);
    await expect(page.getByRole('button', { name: /afficher les noms/i })).toBeVisible();
  });

  test('the shortcut does not fire while typing', async ({ page }) => {
    await withDisplay(page, {});
    await gotoStable(page, '/fr/classes/new');

    // The class-code field: a real text input a teacher types into, on a
    // screen where an accidental toggle would be invisible to them.
    const field = page.locator('input').first();
    await field.click();
    await field.pressSequentially('9D');
    await field.press('Shift+D');

    // Still showing everything: a bare letter shortcut that fired inside a
    // field would toggle the mode while a teacher typed a sheet title.
    await expect(page.locator('html')).not.toHaveAttribute('data-discreet', 'on');
  });
});
