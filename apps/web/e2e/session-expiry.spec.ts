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

    // Before the redirect completes, the row says what happened to it — the same
    // persistent marker a 500 leaves, because from the teacher's side the two
    // are the same event: a judgement they made that the server does not have.
    // A toast alone would not do: it is gone in seconds and they are thirty
    // pages down.
    await expect(
      card.getByText(/non enregistré/i).or(page.getByRole('status').getByText(/n'a pas été enregistrée/i)),
    ).toBeVisible({ timeout: 10_000 });
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

    // The one that landed still reads as landed. This is the assertion that
    // would fail if the 401 handler cleared the whole query cache rather than
    // the session — which is a plausible way to write it, and would throw away
    // work the server already has.
    await expect(
      first.getByRole('radiogroup', { name: /verdict/i }).getByRole('radio', { name: /^faux$/i }),
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
