import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * A differentiation run survives the tab (F4).
 *
 * The proposal has always been durable — `GET /adaptive/proposal/{job_id}`
 * returns it, and the query pins `staleTime: Infinity` precisely because it is
 * expensive to rebuild. What was not durable was the job id that addresses it:
 * it lived in one component's `useState`, so closing the laptop between
 * pressing **Préparer** and reading the result lost the only handle on a plan
 * that was sitting finished in the database. Reopening `/adaptive` offered the
 * empty state and a button that would spend twenty-four more provider calls.
 *
 * A reload is the closest a test can get to a closed laptop: same browser, new
 * page, nothing left in memory.
 */
const ADAPTIVE = '/fr/adaptive';

async function propose(page: import('@playwright/test').Page): Promise<void> {
  await gotoStable(page, ADAPTIVE);
  await page.getByRole('button', { name: /Préparer/i }).click();
  await page
    .getByRole('heading', { name: /Compétences ciblées/i })
    .waitFor({ timeout: 20_000 });
}

test.describe('recovering an adaptive run', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('the job id is in the URL, the way the scan flow does it', async ({ page }) => {
    await propose(page);
    await expect(page).toHaveURL(/[?&]job=/);
  });

  test('a reload comes back to the same proposal instead of the empty state', async ({ page }) => {
    await propose(page);
    const url = page.url();

    await page.reload();
    await page.waitForLoadState('networkidle');

    // The plan is on screen again...
    await expect(page.getByRole('heading', { name: /Compétences ciblées/i })).toBeVisible({
      timeout: 20_000,
    });
    // ...at the same address, and without proposing again. A second POST would
    // mean the teacher had just paid for the whole class a second time.
    expect(page.url()).toBe(url);
    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls.filter((c) => c === 'POST /adaptive/propose')).toHaveLength(0);
    expect(calls.some((c) => c.startsWith('GET /adaptive/proposal/'))).toBe(true);
  });

  test('opening the address in a fresh page reaches the plan', async ({ page, context }) => {
    await propose(page);
    const url = page.url();

    // A genuinely new page: nothing of the first one's React state exists here.
    const second = await context.newPage();
    await second.goto(url);
    await expect(second.getByRole('heading', { name: /Compétences ciblées/i })).toBeVisible({
      timeout: 20_000,
    });
    await second.close();
  });

  /**
   * The list for the case the URL cannot cover: the tab is gone and nobody
   * copied the address. Local to this browser on purpose — `GET /jobs` is
   * scoped to the school and `JobOut` carries no `class_id`, so a server-side
   * list would offer a teacher their colleague's run.
   */
  test('a lost tab can find the run again from the empty state', async ({ page, context }) => {
    await propose(page);

    const fresh = await context.newPage();
    await fresh.addInitScript(() => window.localStorage.setItem('alppy.mock', '1'));
    await gotoStable(fresh, ADAPTIVE);

    // The empty state now carries a way back in.
    await expect(fresh.getByText(/reprises récentes/i)).toBeVisible();
    await fresh.getByRole('button', { name: /\d/ }).first().click();

    await expect(fresh).toHaveURL(/[?&]job=/);
    await expect(fresh.getByRole('heading', { name: /Compétences ciblées/i })).toBeVisible({
      timeout: 20_000,
    });
    await fresh.close();
  });
});
