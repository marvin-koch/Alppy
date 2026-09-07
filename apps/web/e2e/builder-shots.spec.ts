import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * Screenshots of the reworked builder, for the review record.
 *
 * Not assertions — `sheet-builder.spec.ts` holds those. These exist so a human
 * can look at the three states that are hard to describe in prose: the default
 * two-column layout, the same screen with the preview docked, and the chapter
 * outline with its on-demand extraction states.
 */
// Playwright resolves relative paths against apps/web, and these belong with
// the other review screenshots at the repo root.
const SHOTS = '../../docs/reviews/screenshots/builder';

test.describe('builder screenshots', () => {
  // Opt-in: `ALPPY_SHOTS=1 pnpm test:e2e builder-shots`.
  //
  // This spec's only job is to write PNGs into the repository, and a
  // pixel-identical re-render is not guaranteed — so running it as part of the
  // ordinary suite leaves a dirty working tree after every `pnpm test:e2e` and
  // after every CI run. The screenshots are refreshed deliberately, when the
  // screen changes, not as a side effect of running the tests.
  test.skip(!process.env.ALPPY_SHOTS, 'set ALPPY_SHOTS=1 to refresh the screenshots');
  test.skip(({ browserName }) => browserName !== 'chromium', 'one browser is enough');

  test('the three states', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'desktop only');
    await withDisplay(page, {});
    await gotoStable(page, '/fr/sheets/new');
    await page.getByLabel(/document source/i).selectOption({ index: 1 });
    await expect(page.getByRole('heading', { name: /dans le document/i })).toBeVisible();

    const boxes = page.getByRole('checkbox');
    await boxes.nth(0).check();
    await boxes.nth(1).check();
    await boxes.nth(2).check();
    await expect(page.getByText(/3 cochés en tout/)).toBeVisible();

    await page.screenshot({ path: `${SHOTS}/01-preview-closed.png`, fullPage: true });

    await page.getByRole('button', { name: /afficher l'aperçu/i }).click();
    await expect(page.getByRole('heading', { name: /^aperçu$/i })).toBeVisible();
    // The preview is a server round trip behind a debounce.
    await expect(page.locator('iframe')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${SHOTS}/02-preview-open.png`, fullPage: true });

    await page.getByRole('button', { name: /changer de chapitre/i }).click();
    await expect(page.getByText(/indexé, pas encore lu/i).first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/03-chapter-outline.png` });
    await page.keyboard.press('Escape');

    await page.getByRole('button', { name: /ajouter un exercice/i }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/04-add-type.png` });
    await dialog.getByRole('button', { name: /choix multiple/i }).click();
    await page.screenshot({ path: `${SHOTS}/05-add-mcq.png` });
  });

  test('on a phone', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'phone', 'phone only');
    await withDisplay(page, {});
    await gotoStable(page, '/fr/sheets/new');
    await page.getByLabel(/document source/i).selectOption({ index: 1 });
    await expect(page.getByRole('heading', { name: /dans le document/i })).toBeVisible();
    await page.getByRole('checkbox').first().check();
    await page.screenshot({ path: `${SHOTS}/06-phone.png`, fullPage: true });
  });
});
