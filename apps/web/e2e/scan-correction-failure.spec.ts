import { expect, test } from '@playwright/test';

import { gotoStable, showEveryItem, withDisplay } from './helpers';

/**
 * A correction that does not land says so.
 *
 * The verdict controls on this screen are driven by server data, so a `PATCH`
 * that comes back 500 left the cached detection untouched and the control
 * silently re-rendered the MACHINE's reading. A teacher pressed **Faux**, saw
 * **Juste** a frame later, read it as a repaint, and confirmed the pile — at
 * which point the model's verdict became the grade with nothing recording that
 * anyone had disagreed. Nothing anywhere read `correct.isError`.
 *
 * The 500 is injected through the mock's own seam rather than Playwright's
 * `page.route`, because in mock mode `apiRequest` never reaches `fetch`: it
 * calls `handleMock` in-process, so there is no network for a route handler to
 * intercept. See `MockFailure` in `lib/api/mock/handlers.ts`.
 *
 * The network-drop case is NOT this test. That one the shell already handles,
 * with an offline bar that says corrections already sent are safe. This is the
 * case where the API is reachable and answering "no".
 */
const SCAN = '/fr/scans/00000000-0000-4000-8000-000000000800';

/** Fail every correction on this page, from before the first paint. */
async function failCorrections(
  page: import('@playwright/test').Page,
  times?: number,
): Promise<void> {
  await page.addInitScript((n) => {
    (globalThis as { __alppyMockFail?: unknown[] }).__alppyMockFail = [
      { method: 'PATCH', pattern: '/detections/', status: 500, code: 'server_error', times: n },
    ];
  }, times ?? undefined);
}

test.describe('a correction the API refuses', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('reports the failure in the accessibility tree instead of reverting in silence', async ({
    page,
  }) => {
    await failCorrections(page);
    await gotoStable(page, SCAN);
    // Settled items are hidden by default now (G12).
    await showEveryItem(page);

    const card = page.locator('[data-open-answer]').first();
    const verdict = card.getByRole('radiogroup', { name: /verdict/i });
    await expect(verdict.getByRole('radio', { name: /^juste$/i })).toHaveAttribute(
      'aria-checked',
      'true',
    );

    await verdict.getByRole('radio', { name: /^faux$/i }).click();

    // The toast lives in a polite live region that is always mounted, so this is
    // what a screen reader is told — not merely something that is on screen.
    const alerts = page.getByRole('status').or(page.locator('[aria-live]'));
    await expect(alerts.getByText(/n'a pas été enregistrée/i)).toBeVisible();

    // And the row itself keeps saying so, because a toast is gone in seconds and
    // a teacher reviewing thirty pages will have scrolled past it.
    await expect(card.getByText(/non enregistré/i)).toBeVisible();

    // The machine's verdict is back in the control -- which is correct, it IS
    // what the server holds -- but it is no longer the only thing the screen says.
    await expect(verdict.getByRole('radio', { name: /^juste$/i })).toHaveAttribute(
      'aria-checked',
      'true',
    );
  });

  test('the toast offers a retry, and a retry that succeeds clears the marker', async ({
    page,
  }) => {
    // Fail once. The retry meets a working API, the way a blip actually behaves.
    await failCorrections(page, 1);
    await gotoStable(page, SCAN);
    // Settled items are hidden by default now (G12).
    await showEveryItem(page);

    const card = page.locator('[data-open-answer]').first();
    const verdict = card.getByRole('radiogroup', { name: /verdict/i });
    await verdict.getByRole('radio', { name: /^faux$/i }).click();

    await expect(card.getByText(/non enregistré/i)).toBeVisible();

    await page
      .getByRole('button', { name: /^Réessayer$/i })
      .first()
      .click();

    await expect(card.getByText(/non enregistré/i)).toHaveCount(0);
    await expect(verdict.getByRole('radio', { name: /^faux$/i })).toHaveAttribute(
      'aria-checked',
      'true',
    );
  });
});
