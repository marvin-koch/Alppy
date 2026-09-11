import { expect, test } from '@playwright/test';

import { withDisplay } from './helpers';

/**
 * A failure a teacher can report.
 *
 * `ApiError.requestId` is parsed off every failed envelope and, until this pass,
 * reached the screen only through the `global-error` boundary — the boundary least
 * likely of all of them to fire (G18). A support conversation that starts with an
 * id is a different conversation from one that starts with "it said it did not
 * work".
 *
 * The failure is injected through the mock's own seam: in fixture mode
 * `apiRequest` never reaches `fetch`, so there is no network for `page.route` to
 * intercept. See `MockFailure` in `lib/api/mock/handlers.ts`.
 */
test.describe('a failed screen names the request', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
    await page.addInitScript(() => {
      (globalThis as { __alppyMockFail?: unknown[] }).__alppyMockFail = [
        { method: 'GET', pattern: '/classes', status: 500, code: 'server_error' },
      ];
    });
  });

  test('shows the request id, in monospace, under the message', async ({ page }) => {
    await page.goto('/fr/classes');

    // The teacher-facing sentence comes first and is the one addressed to them.
    await expect(page.getByRole('heading', { level: 3 })).toBeVisible();

    // The id is present and is a real value, not an empty element.
    const id = page.locator('[data-request-id]');
    await expect(id).toBeVisible();
    await expect(id).not.toBeEmpty();
    await expect(id).toHaveClass(/mono/);
  });

  /** It must never be the loudest thing on the error: it is the only string there
   *  that is not addressed to the teacher. */
  test('does not displace the sentence that is for the teacher', async ({ page }) => {
    await page.goto('/fr/classes');

    const heading = page.getByRole('heading', { level: 3 });
    const id = page.locator('[data-request-id]');
    const headingBox = await heading.boundingBox();
    const idBox = await id.boundingBox();

    expect(headingBox).not.toBeNull();
    expect(idBox).not.toBeNull();
    // Below the title, and smaller than it.
    expect(idBox!.y).toBeGreaterThan(headingBox!.y);
    expect(idBox!.height).toBeLessThan(headingBox!.height);
  });
});
