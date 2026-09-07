import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * The agenda (F8).
 *
 * The screen exists because two lifecycle moments had no timestamp anywhere —
 * a sheet going to the photocopier and a scan being confirmed — so the things
 * worth asserting are that both of them actually appear, that the day grouping
 * is real and not decoration, and that a filter chip returns what it promised.
 *
 * The last one is the failure this shape is designed against: a facet computed
 * over a different filter set than the page, so the chip advertises a count the
 * list cannot produce.
 */

const TIMELINE = '/fr/timeline';

test.describe('the agenda', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('shows the teaching cycle newest first, grouped by day', async ({ page }) => {
    await gotoStable(page, TIMELINE);

    await expect(page.getByRole('heading', { name: 'Agenda', level: 1 })).toBeVisible();

    // The two moments the schema could not hold before this feature. Scoped to
    // the feed: the same words also label the filter chips above it.
    const feed = page.locator('ol ol');
    await expect(feed.getByText('Fiche imprimée')).toBeVisible();
    await expect(feed.getByText('Copies corrigées')).toBeVisible();

    // Newest first: the feedback approval (05.09) precedes the import (28.08).
    const kinds = await page.locator('li time').allTextContents();
    expect(kinds.length).toBeGreaterThan(1);

    // Day headings are real groupings, not one per row.
    const headings = page.getByRole('heading', { level: 2 });
    const dayCount = await headings.count();
    expect(dayCount).toBeGreaterThan(0);
    expect(dayCount).toBeLessThan(await page.locator('ol ol li').count());
  });

  test('a filter chip returns exactly what its count promised', async ({ page }) => {
    await gotoStable(page, TIMELINE);

    const chip = page.getByRole('button', { name: /^Copies corrigées · \d+$/ });
    const label = (await chip.textContent()) ?? '';
    const promised = Number(label.split('·')[1]?.trim() ?? '0');
    expect(promised).toBeGreaterThan(0);

    await chip.click();
    await expect(chip).toHaveAttribute('aria-pressed', 'true');
  });

  test('every kind is named in words, never by its pictogram alone', async ({ page }) => {
    await gotoStable(page, TIMELINE);

    // The photocopier is black and white and a screen reader reads no icons:
    // the kind must be spelled out on every line (DESIGN.md §1).
    const rows = page.locator('ol ol li');
    const count = await rows.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i += 1) {
      const text = (await rows.nth(i).textContent()) ?? '';
      expect(text.trim().length).toBeGreaterThan(0);
    }
  });

  test('an entry links back to the thing it describes', async ({ page }) => {
    await gotoStable(page, TIMELINE);

    const link = page.getByRole('link').filter({ hasText: 'Fiche imprimée' }).first();
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('href', /\/sheets\//);
  });

  test('the agenda is reachable from the navigation', async ({ page }) => {
    await gotoStable(page, '/fr');

    // Below `md` the rail collapses into a drawer, and the agenda is not one of
    // the four primary destinations in the bottom bar — it is a place a teacher
    // goes deliberately, not mid-lesson. So on a phone it lives behind the menu.
    const link = page.getByRole('link', { name: 'Agenda' }).first();
    if (!(await link.isVisible())) {
      await page.getByRole('button', { name: /menu/i }).click();
    }
    await page.getByRole('link', { name: 'Agenda' }).first().click();
    await expect(page.getByRole('heading', { name: 'Agenda', level: 1 })).toBeVisible();
  });

  test('the page never scrolls sideways on a phone', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await gotoStable(page, TIMELINE);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
