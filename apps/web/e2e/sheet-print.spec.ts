import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * There is one door to paper, and it is the PDF.
 *
 * This is the end-to-end half of the F1 fix (`lib/print.ts` is the unit half).
 * The screen used to carry two print paths that were not equivalent: **Imprimer**
 * called `print()` on the preview iframe and then recorded the sheet as printed,
 * while only `render_sheet` writes the `AnswerBoxPlacement` rows the scan job
 * crops a written answer from. A fiche could therefore be printed, sat, and
 * photographed with every written answer ungradeable — and the agenda would say
 * it had been printed.
 *
 * So what is asserted here is an absence as much as a presence: on a sheet
 * whose PDF is not current there is no control that prints anything, and none
 * that records a print.
 */
const SHEET_ID = '00000000-0000-4000-8000-000000000600';

test.describe('printing a sheet', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('an unrendered sheet offers no way to print, and says why', async ({ page }) => {
    await gotoStable(page, `/fr/sheets/${SHEET_ID}`);

    // The primary action builds the document. There is no Imprimer at all:
    // not a disabled one, not one that falls through to a new tab.
    await expect(page.getByRole('button', { name: /générer les pdf/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /imprimer/i })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^imprimer$/i })).toHaveCount(0);

    // And the refusal is explained rather than merely enacted.
    await expect(page.getByText(/l'impression passe par le pdf/i)).toBeVisible();
  });

  test('printing becomes possible only once the PDF exists, and only then is a print recorded', async ({
    page,
  }) => {
    await gotoStable(page, `/fr/sheets/${SHEET_ID}`);

    // Nothing has been recorded by merely opening the screen.
    let calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls.some((c) => c.includes('/printed'))).toBe(false);

    await page.getByRole('button', { name: /générer les pdf/i }).click();

    // The mock's render job writes the PDF keys and `rendered_at` onto the
    // sheet, exactly as the worker does; the screen re-reads the sheet when the
    // job finishes. Now — and not before — there is something to print.
    const printLink = page.getByRole('link', { name: /imprimer/i });
    await printLink.waitFor({ state: 'visible', timeout: 15_000 });
    await expect(printLink).toHaveAttribute('href', /\.pdf$/);
    await expect(page.getByText(/l'impression passe par le pdf/i)).toHaveCount(0);

    calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls.some((c) => c.includes('/render'))).toBe(true);
  });

  test('the preview is an aperçu: it is never what gets printed', async ({ page }) => {
    // The preview frame loads its document straight from the API — a browser
    // navigation, which the fixture layer intercepts nothing of, since that
    // layer sits inside `apiRequest`. So the document is served here instead.
    // Which also means: this is the only place in the suite where the preview
    // frame renders at all.
    await page.route('**/sheets/*/preview*', (route) =>
      route.fulfill({
        contentType: 'text/html; charset=utf-8',
        body: '<!doctype html><html lang="fr"><body><section class="print-page">Fiche</section></body></html>',
      }),
    );
    await gotoStable(page, `/fr/sheets/${SHEET_ID}`);

    // The frame is the API's own print document — that is deliberate, and it is
    // what keeps the preview from drifting from the paper (F1-review P1-2).
    // What it must not be is printable: nothing drives this frame any more, so
    // it no longer asks for `allow-modals` — which is precisely what a
    // sandboxed frame needs in order to open a print dialog.
    const frame = page.locator('iframe').first();
    await expect(frame).toBeVisible();
    await expect(frame).toHaveAttribute('sandbox', 'allow-same-origin');
  });

  test('a preview the browser refuses to show says so instead of showing blank paper', async ({
    page,
  }) => {
    // The failure this reproduces is the compose default before the CSP fix:
    // `frame-src 'self'` blocked the API's document while `connect-src` let the
    // preview's own `fetch` check through, so the check passed and the teacher
    // got a blank A4 with no error — and the print button of the day fell
    // through to `window.open`, which worked. Here the frame simply never
    // loads, which is the same thing from the screen's point of view.
    await page.route('**/sheets/*/preview*', async (route) => {
      if (route.request().resourceType() === 'document') return route.abort();
      return route.fulfill({ contentType: 'text/html', body: '<html></html>' });
    });
    await gotoStable(page, `/fr/sheets/${SHEET_ID}`);

    await expect(page.getByRole('alert')).toBeVisible({ timeout: 15_000 });
  });
});
