import { expect, test } from '@playwright/test';

import { gotoStable, showEveryItem, withDisplay } from './helpers';

/**
 * A session that dies in the middle of marking a pile.
 *
 * Twelve hours is the cookie's life (`ALPPY_SESSION_MAX_AGE_S`), and a teacher
 * who opened a pile before lunch and comes back to it after school is inside
 * the ordinary case, not the edge of one. What must not happen is the thing
 * that happens by default: a `PATCH` comes back 401, the control silently
 * re-renders the machine's reading, and the teacher goes on marking into a
 * session that no longer exists.
 *
 * **These tests could not be written until the transport was fixed (T11).**
 * `apiRequest` returned the mock's answer directly, before the line that calls
 * `noteUnauthorized`, so in mock mode — which is every E2E run — a 401 never
 * reached the redirect handler at all. Not "untested": unreachable. The bug was
 * in the test seam rather than in the product, which is the kind that survives
 * longest, because everything that looks at the product looks fine.
 *
 * The 401 is injected through the mock's own `MockFailure` seam for the reason
 * `scan-correction-failure.spec.ts` gives: in mock mode `apiRequest` never
 * reaches `fetch`, so `page.route` has no network to intercept.
 */
const SCAN = '/fr/scans/00000000-0000-4000-8000-000000000800';

async function expireTheSession(
  page: import('@playwright/test').Page,
  times?: number,
): Promise<void> {
  await page.addInitScript((n) => {
    (globalThis as { __alppyMockFail?: unknown[] }).__alppyMockFail = [
      { method: 'PATCH', pattern: '/detections/', status: 401, code: 'unauthorized', times: n },
    ];
  }, times ?? undefined);
}

/**
 * Wait for the 401 to land the teacher on the login screen, then sign back in.
 *
 * The login screen returns to `?from=`, client-side, so the fixture layer's
 * state — the corrections that DID land — is still there on the way back. The
 * injected failure is lifted first, or the review screen's own reads would be
 * refused again.
 */
async function signBackIn(page: import('@playwright/test').Page): Promise<void> {
  await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  await page.evaluate(() => {
    (globalThis as { __alppyMockFail?: unknown[] }).__alppyMockFail = [];
  });
  await page.getByLabel(/e-?mail/i).fill('demo@alppy.ch');
  await page.locator('input[type="password"]').fill('alppy-demo-2026');
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/scans\//, { timeout: 10_000 });
  await showEveryItem(page);
}

test.describe('a session that expires mid-review', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('the teacher is sent to the login screen rather than left marking into nothing', async ({
    page,
  }) => {
    await expireTheSession(page);
    await gotoStable(page, SCAN);
    await showEveryItem(page);

    const card = page.locator('[data-open-answer]').first();
    await card.getByRole('radiogroup', { name: /verdict/i }).getByRole('radio', { name: /^faux$/i }).click();

    // The whole point of the fix: a 401 from the fixture layer now travels the
    // same path a 401 from the API travels, so the handler `Providers`
    // registered actually runs.
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });

  test('the correction that was in flight is marked, not silently lost', async ({ page }) => {
    await expireTheSession(page);
    await gotoStable(page, SCAN);
    await showEveryItem(page);

    const card = page.locator('[data-open-answer]').first();
    await card.getByRole('radiogroup', { name: /verdict/i }).getByRole('radio', { name: /^faux$/i }).click();

    // The row says what happened to it — the same persistent marker a 500
    // leaves, because from the teacher's side the two are the same event: a
    // judgement they made that the server does not have.
    //
    // Asserted AFTER signing back in, and that is the fix, not a loosening. The
    // 401 handler redirects in the same tick, so the old in-place assertion was
    // racing the navigation: it passed only when it caught the sub-100 ms
    // window before the screen unmounted, and failed about one run in three.
    // Worse, the window was all there was — the record lived in component
    // state and died with the redirect, so a teacher who signed back in found
    // the machine's reading and no sign they had ever disagreed. It is kept in
    // the tab's storage now (`lib/unsavedCorrections.ts`), and this is where a
    // teacher would actually look for it.
    await signBackIn(page);
    const returned = page.locator('[data-open-answer]').first();
    await expect(returned.getByText(/non enregistré/i)).toBeVisible({ timeout: 10_000 });

    // And it can be sent again from the card. The toast that carried the only
    // retry did not survive the redirect, and re-pressing the verdict is no
    // substitute when it agrees with the model's — that radio is already
    // checked, and a click on it sends nothing.
    await returned.getByRole('button', { name: /réessayer/i }).click();
    await expect(returned.getByText(/non enregistré/i)).toBeHidden({ timeout: 10_000 });
    await expect(
      returned.getByRole('radiogroup', { name: /verdict/i }).getByRole('radio', { name: /^faux$/i }),
    ).toHaveAttribute('aria-checked', 'true');
  });

  test('corrections that landed before the expiry are still there on return', async ({ page }) => {
    // Only the SECOND correction meets the dead session. The first is a normal
    // save, and it has to survive — a teacher who marked twenty pages before
    // lunch must not find them gone because the twenty-first failed.
    await page.addInitScript(() => {
      (globalThis as { __alppyMockFail?: unknown[] }).__alppyMockFail = [];
    });
    await gotoStable(page, SCAN);
    await showEveryItem(page);

    const cards = page.locator('[data-open-answer]');
    const first = cards.first();
    await first.getByRole('radiogroup', { name: /verdict/i }).getByRole('radio', { name: /^faux$/i }).click();
    await expect(
      first.getByRole('radiogroup', { name: /verdict/i }).getByRole('radio', { name: /^faux$/i }),
    ).toHaveAttribute('aria-checked', 'true');

    // Now the session dies, and a second correction is attempted.
    await page.evaluate(() => {
      (globalThis as { __alppyMockFail?: unknown[] }).__alppyMockFail = [
        { method: 'PATCH', pattern: '/detections/', status: 401, code: 'unauthorized' },
      ];
    });
    const second = cards.nth(1);
    if (await second.count()) {
      await second
        .getByRole('radiogroup', { name: /verdict/i })
        .getByRole('radio', { name: /^faux$/i })
        .click();
    }

    // The one that landed still reads as landed — checked on the way back in,
    // where "still there on return" can actually be observed. Reading it in
    // place raced the redirect the 401 had just started, and failed with
    // "element(s) not found" whenever the screen unmounted first.
    await signBackIn(page);
    await expect(
      page
        .locator('[data-open-answer]')
        .first()
        .getByRole('radiogroup', { name: /verdict/i })
        .getByRole('radio', { name: /^faux$/i }),
    ).toHaveAttribute('aria-checked', 'true');
  });

  test('a 401 from the session PROBE does not bounce the login screen off itself', async ({
    page,
  }) => {
    // `/auth/me` is the app ASKING whether there is a session; a 401 is that
    // question's answer, not a session that has just died. `isSessionProbe`
    // exists for this, and now that mock 401s reach `noteUnauthorized` the
    // exemption is finally reachable by a test too — it went from untested to
    // load-bearing in the same change.
    await page.addInitScript(() => {
      (globalThis as { __alppyMockFail?: unknown[] }).__alppyMockFail = [
        { method: 'GET', pattern: '/auth/me', status: 401, code: 'unauthorized' },
      ];
    });
    await gotoStable(page, '/fr/login');

    await page.waitForTimeout(500);
    await expect(page).toHaveURL(/\/login/);
  });
});
