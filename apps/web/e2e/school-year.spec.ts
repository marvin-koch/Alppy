import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * The school year is reachable, and a past year says so loudly.
 *
 * The API had served `GET /school-years`, `school_year_id` on `/home`, `/classes`,
 * `/sheets` and `/scans`, and `as_of` on five mastery reads since the backend
 * pass. `endpoints.ts` typed all of it, with explanatory comments. Nothing above
 * that layer touched any of it: no hook, no screen, no cache key. A reader who
 * saw `asOf` typed in `endpoints.ts` reasonably assumed it was wired up
 * somewhere, which is worse than an honest absence (audit 05 G3).
 *
 * Two things have to hold, and the second is the one that matters. The year has
 * to reach the REQUEST — otherwise the filter does nothing — and it has to reach
 * the CACHE KEY, or switching year re-renders the year you left from memory and a
 * teacher reads last year's figures under this year's heading.
 *
 * `fixtures.classes` has a class in each year (`schoolYears[0]` and `[1]`), so a
 * working filter and an ignored one produce different screens. Before this pass
 * every fixture class sat in the current year and no test could have told them
 * apart.
 */
const CURRENT = '2026/27';
const PAST = '2025/26';

/** The class list, not the switcher: the switcher shows the current class's code
 *  too, and `getByText('7B')` matches both. */
function classCard(page: import('@playwright/test').Page, code: string) {
  return page.getByRole('heading', { level: 2 }).filter({ hasText: code });
}

async function calls(page: import('@playwright/test').Page): Promise<string[]> {
  return page.evaluate(() => globalThis.__alppyMockCalls ?? []);
}

test.describe('the school year', () => {
  // Desktop only, and deliberately. On a phone the whole switcher lives behind
  // the drawer, and opening it before each of these would add six copies of the
  // same plumbing for no extra signal: `f7-navigation.spec.ts` already asserts
  // the year row is reachable in the drawer, on the phone project. What is under
  // test here is the dimension's behaviour, not where the control sits.
  test.beforeEach(async ({ page }, testInfo) => {
    // In `beforeEach`, not at describe level: a describe-scope conditional skip
    // is handed the fixtures only, and reading `testInfo.project` there throws.
    test.skip(testInfo.project.name !== 'desktop', 'the switcher is in the drawer on a phone');
    await withDisplay(page, {});
  });

  test('is offered in the switcher, above the class', async ({ page }) => {
    await gotoStable(page, '/fr/classes');

    const year = page.getByLabel(/année scolaire/i);
    await expect(year).toBeVisible();
    await expect(year).toHaveValue(/.+/);

    // Above the class row, in DOM order — the year decides what the class row is
    // even choosing between.
    const labels = await page
      .locator('[data-scope-switcher] select')
      .evaluateAll((els) => els.map((el) => el.getAttribute('aria-label') ?? ''));
    const yearAt = labels.findIndex((l) => /année scolaire/i.test(l));
    const classAt = labels.findIndex((l) => /classe/i.test(l));
    expect(yearAt).toBeGreaterThanOrEqual(0);
    expect(classAt).toBeGreaterThan(yearAt);
  });

  test('reaches the request, and the URL carries it', async ({ page }) => {
    await gotoStable(page, '/fr/classes');

    await page.getByLabel(/année scolaire/i).selectOption({ label: PAST });

    await expect(page).toHaveURL(/[?&]year=/);
    await expect
      .poll(async () => (await calls(page)).some((c) => c.includes('school_year_id=')))
      .toBe(true);
  });

  /** The cache half. Switching to a past year and back must not show the other
   *  year's roster from memory — which is what a missing key segment does. */
  test('shows a different class list per year, not the cached one', async ({ page }) => {
    await gotoStable(page, '/fr/classes');
    await expect(classCard(page, '7B')).toBeVisible();

    await page.getByLabel(/année scolaire/i).selectOption({ label: PAST });

    // Last year's class appears; this year's two are gone.
    await expect(classCard(page, '7A')).toBeVisible();
    await expect(classCard(page, '7B')).toHaveCount(0);

    await page.getByLabel(/année scolaire/i).selectOption({ label: CURRENT });

    await expect(classCard(page, '7B')).toBeVisible();
    await expect(classCard(page, '7A')).toHaveCount(0);
  });

  test('says so in a banner, not a chip, and offers the way back', async ({ page }) => {
    await gotoStable(page, '/fr/classes');
    await expect(page.locator('[data-past-year]')).toHaveCount(0);

    await page.getByLabel(/année scolaire/i).selectOption({ label: PAST });

    const banner = page.locator('[data-past-year]');
    await expect(banner).toBeVisible();
    // Names the year in words, not by colour alone (DC-colour-08).
    await expect(banner).toContainText(PAST);
    // And it is announced, not merely drawn.
    await expect(banner).toHaveAttribute('role', 'status');

    await banner.getByRole('button', { name: new RegExp(CURRENT.replace('/', '\\/')) }).click();

    await expect(page.locator('[data-past-year]')).toHaveCount(0);
    await expect(classCard(page, '7B')).toBeVisible();
  });

  test('survives a reload, because the year is sticky', async ({ page }) => {
    await gotoStable(page, '/fr/classes');
    await page.getByLabel(/année scolaire/i).selectOption({ label: PAST });
    await expect(page.locator('[data-past-year]')).toBeVisible();

    // A bare route, with no `?year=`: the stored year is what brings it back.
    await gotoStable(page, '/fr/classes');

    await expect(page.locator('[data-past-year]')).toBeVisible();
    await expect(page.getByLabel(/année scolaire/i)).toHaveValue(/.+/);
  });

  /** `as_of` is a different parameter from `school_year_id`, and the mastery
   *  reads are the ones that need it: without it a past year's attempts decay by
   *  however long ago the year ended and the class looks as if it learnt nothing. */
  test('sends as_of on a mastery read for a past year, and not for the current one', async ({
    page,
  }) => {
    await gotoStable(page, '/fr/classes');
    await page.getByLabel(/année scolaire/i).selectOption({ label: CURRENT });
    await classCard(page, '7B').first().click();
    await expect
      .poll(async () => (await calls(page)).some((c) => c.includes('/mastery')))
      .toBe(true);
    expect((await calls(page)).some((c) => c.includes('as_of='))).toBe(false);

    await page.getByLabel(/année scolaire/i).selectOption({ label: PAST });

    await expect.poll(async () => (await calls(page)).some((c) => c.includes('as_of='))).toBe(true);
  });
});
