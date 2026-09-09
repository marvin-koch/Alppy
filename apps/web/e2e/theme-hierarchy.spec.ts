import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * `Class → Branch → Competence → Theme → Sheets`, where it is load-bearing.
 *
 * Two of these guard constraints that are easy to erode by accident, and both
 * read the mock's call log rather than the DOM where the DOM would lie:
 *
 * - **DC-content-06.** The builder is rooted on the Theme now. `ExercisePicker`
 *   used to keep "nothing is unreachable" by having no theme filter at all,
 *   because `Exercise.chapter_id` is inferred and null on a large minority of a
 *   real textbook. The counted "Sans thème" row is what keeps that promise, and
 *   it has to actually send `chapter_id=none` — a filter that changes React
 *   state and never reaches the API looks identical on screen and is broken.
 *
 * - A sheet must not be filable under that row. It answers a question about the
 *   corpus, not about where a sheet belongs.
 */
test.describe('the curriculum hierarchy', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('the untagged bucket is offered, counted, and actually filters', async ({
    page,
  }) => {
    await gotoStable(page, '/fr/sheets/new');
    // The exercise list is per-document (`/sources/{id}/exercises`), so the
    // theme filter only reaches the API once there is a document to filter.
    await page.getByLabel(/document source/i).selectOption({ index: 1 });
    await expect(page.getByRole('heading', { name: /dans le document/i })).toBeVisible();

    await page.getByRole('button', { name: /changer de thème/i }).click();

    // Counted, and pinned at the root of the tree rather than inside a
    // Competence — a teacher must be able to reach it without guessing which
    // part of the programme an untagged exercise would have belonged to.
    const bucket = page.getByRole('button', { name: /sans thème \(\d+\)/i });
    await expect(bucket).toBeVisible();
    await bucket.click();

    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(page.getByText(/sans thème \(\d+\)/i)).toBeVisible();

    // The sentinel reached the API. Absent would mean "no theme filter", which
    // is a different answer and would show the tagged rows too.
    await expect
      .poll(async () => {
        const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
        return calls.some((c) => c.includes('chapter_id=none'));
      })
      .toBe(true);
  });

  test('a sheet cannot be filed under "sans thème"', async ({ page }) => {
    await gotoStable(page, '/fr/sheets/new');
    await page.getByRole('button', { name: /changer de thème/i }).click();
    await page.getByRole('button', { name: /sans thème \(\d+\)/i }).click();

    // Even with the bucket selected, generating stays closed: `unfiled` is
    // where an unfiled sheet is STORED, never where a new one is filed.
    await expect(page.getByRole('button', { name: /générer/i })).toBeDisabled();
  });

  test('choosing a real theme opens the way to generating', async ({ page }) => {
    await gotoStable(page, '/fr/sheets/new');
    await page.getByRole('button', { name: /changer de thème/i }).click();

    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', { name: /^fractions$/i }).click();
    await expect(dialog).toBeHidden();

    // The picker summarises the choice rather than still inviting one.
    await expect(page.getByText(/^fractions$/i).first()).toBeVisible();

    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls.some((c) => c.includes('/tree'))).toBe(true);
  });

  test('the class dashboard shows the programme beside the grid', async ({ page }) => {
    await gotoStable(page, '/fr/classes');
    await page.getByRole('link', { name: /7B/ }).first().click();

    // Scope every assertion to the tree itself: the sort <select> also
    // contains band words, hidden inside its options.
    const tree = page
      .getByRole('heading', { name: /programme/i })
      .locator('xpath=ancestor::*[contains(@class,"ard-card")][1]');

    await expect(tree).toBeVisible();
    // A band never travels as a bare colour: the written word is always there.
    await expect(
      tree.getByText(/acquis|à revoir|fragile|s'efface|pas encore vu/i).first(),
    ).toBeVisible();
    // And the bucket for sheets nobody filed stays visible rather than hidden.
    await expect(tree.getByText(/non classé/i).first()).toBeVisible();
  });
});
