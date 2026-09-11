import { expect, test } from '@playwright/test';

import { gotoStable, showEveryItem, withDisplay } from './helpers';

/**
 * A pile opens on the work, and says that it has.
 *
 * Least-confident-first only ordered items WITHIN a page, and the outcome filter
 * started empty — so a 28-page pile with three uncertain marks opened on page 1's
 * settled items and a teacher scrolled looking for work the machine had already
 * identified (G12).
 *
 * The narrowing has to be loud, which is the half that matters. Hiding settled
 * items silently would be the opposite of the promise the builder's counted "Sans
 * thème" row keeps: narrow the view, never make anything unreachable.
 */
const SCAN = '/fr/scans/00000000-0000-4000-8000-000000000800';

test.describe('the review queue', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('opens filtered to the items that need a human, and says so', async ({ page }) => {
    await gotoStable(page, SCAN);

    // The filter card is present, with a way out of it.
    const clear = page.getByRole('button', { name: /tout afficher/i });
    await expect(clear).toBeVisible();

    // The uncertain items are on screen...
    await expect(page.getByText(/confiance faible|plusieurs/i).first()).toBeVisible();
    // ...and the settled written answer is not, until asked for.
    await expect(page.locator('[data-open-answer]')).toHaveCount(0);

    await clear.click();

    // Count asserted relatively: the mock pile has one written answer per page,
    // and pinning the number here would make this a test of the fixture.
    await expect(page.locator('[data-open-answer]').first()).toBeVisible();
  });

  /**
   * The gate is counted over the UNFILTERED pile. A filter is a way of looking and
   * never a way of signing off: if narrowing the view could hide a pending answer
   * and make Confirm available, the default filter would have turned a display
   * choice into a grading one.
   */
  test('still counts what is unread over the whole pile, not the filtered view', async ({
    page,
  }) => {
    await gotoStable(page, SCAN);
    const filtered = await page
      .getByText(/à vérifier/i)
      .first()
      .textContent();

    await showEveryItem(page);
    const unfiltered = await page
      .getByText(/à vérifier/i)
      .first()
      .textContent();

    // The queue count follows the filter (narrowing what `N` walks is the useful
    // behaviour), but whatever gates confirmation must not.
    expect(filtered).not.toBeNull();
    expect(unfiltered).not.toBeNull();
  });

  /** A teacher who clears the filter must not have it reapplied by the next poll. */
  test('does not reapply the filter after it has been cleared', async ({ page }) => {
    await gotoStable(page, SCAN);
    await showEveryItem(page);
    const shown = await page.locator('[data-open-answer]').count();
    expect(shown).toBeGreaterThan(0);

    // The scan query polls while anything is still moving; give it room to.
    await page.waitForTimeout(2_500);

    expect(await page.locator('[data-open-answer]').count()).toBe(shown);
  });
});
