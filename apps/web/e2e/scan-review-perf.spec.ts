import { expect, test } from '@playwright/test';

import { gotoStable, showEveryItem, withDisplay } from './helpers';

/**
 * Moving the selection re-renders one page card, not the whole pile.
 *
 * Audit 05 §12.2 is explicit that G11 was reasoned and not measured: "I
 * established that thirty `PageCard`s and ~1 000 overlay buttons re-render per
 * `setSelected`; I did not measure a frame." This is the measurement.
 *
 * It counts RENDERS, not milliseconds and not DOM mutations. A frame budget on a
 * CI runner measures the runner. And a mutation observer — the obvious approach,
 * which was tried first — measures nothing at all here: React reconciles an
 * identical re-render to zero DOM mutations, so twenty-nine wasted renders and
 * none look exactly the same from the outside. That is precisely the difference
 * `memo` exists to make, which is why this needs the counting seam in
 * `PageCard` (`__alppyRenderCounts`, the same shape as `__alppyMockCalls`).
 */
const SCAN = '/fr/scans/00000000-0000-4000-8000-000000000800';

type Counts = Record<string, number>;

async function startCounting(page: import('@playwright/test').Page): Promise<void> {
  await page.evaluate(() => {
    (globalThis as { __alppyRenderCounts?: Counts }).__alppyRenderCounts = {};
  });
}

async function countsSince(page: import('@playwright/test').Page): Promise<Counts> {
  return page.evaluate(
    () => (globalThis as { __alppyRenderCounts?: Counts }).__alppyRenderCounts ?? {},
  );
}

test.describe('the review screen under a selection change', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'one measurement is enough');
    await withDisplay(page, {});
  });

  test('pressing N re-renders at most two cards, whatever the pile size', async ({ page }) => {
    await gotoStable(page, SCAN);
    await showEveryItem(page);

    // Counting starts AFTER the first paint, so the initial render of every card
    // is not mistaken for waste.
    await startCounting(page);
    await page.keyboard.press('n');
    await page.waitForTimeout(300);

    const counts = await countsSince(page);
    const rendered = Object.entries(counts).filter(([, n]) => n > 0);

    // At most two: the card losing the highlight and the card gaining it. Before
    // the fix, every card in the pile received the raw `selected` value and
    // re-rendered — thirty cards and roughly a thousand overlay buttons to move
    // one outline.
    // Two-sided on purpose. The upper bound is the fix; the lower bound is what
    // stops this passing vacuously — an empty object satisfies `<= 2` perfectly,
    // and a seam that observed nothing would look identical to a perfect memo.
    expect(
      rendered.length,
      `cards re-rendered on one selection change: ${JSON.stringify(counts)}`,
    ).toBeGreaterThanOrEqual(1);
    expect(
      rendered.length,
      `cards re-rendered on one selection change: ${JSON.stringify(counts)}`,
    ).toBeLessThanOrEqual(2);
  });
});
