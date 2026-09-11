import { expect, test } from '@playwright/test';

import { withDisplay } from './helpers';

/**
 * The App Router boundaries (F6).
 *
 * There were none — no `error.tsx`, no `not-found.tsx`, at any level — while
 * `notFound()` is genuinely called, including by the locale layout for an
 * unknown locale. So every typo'd URL and every stale bookmark got Next's own
 * 404: English, unstyled, outside the app shell, on a product that is
 * otherwise carefully trilingual. The strings to fix it had been translated
 * three times and referenced nowhere (F30).
 *
 * These assert the wiring, which is the half a unit test cannot see: that Next
 * finds these files, that the miss is routed INTO the locale segment so the
 * teacher's own language answers, and that the app shell survives it.
 *
 * Not asserted: the HTTP status. `notFound()` raised inside a streamed dynamic
 * render lands after the shell's 200 has gone out, so these answer 200. That is
 * Next's behaviour, not a choice made here; it is recorded rather than pinned,
 * because a future Next may well change it and this suite should not fail when
 * it improves.
 */
test.describe('the not-found boundaries', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('a bad path answers in the teacher’s own language, inside the app shell', async ({
    page,
  }) => {
    await page.goto('/fr/ceci-nexiste-pas');

    // The catalogue's own strings — `errors.notFound.*`, previously dead.
    await expect(page.getByRole('heading', { name: /page introuvable/i })).toBeVisible();
    await expect(page.getByText(/n'existe pas ou vous n'y avez pas accès/i)).toBeVisible();

    // Still Alppy: the shell rendered around the boundary, so the teacher is
    // not stranded on a bare page. Counted rather than checked for visibility —
    // the rail and the bottom tabs trade places at the `lg` breakpoint, so
    // which one is on screen depends on the viewport this runs in.
    expect(await page.locator('nav').count()).toBeGreaterThan(0);

    // And a way out that is a real link rather than the browser's back button.
    await page.getByRole('link', { name: /retour à l'accueil/i }).click();
    await expect(page).toHaveURL(/\/fr$/);
  });

  /**
   * The reason `[locale]/[...rest]/page.tsx` exists. Without it the miss never
   * enters the locale segment: Next 404s at the root, outside the intl
   * provider, and says "Page introuvable" to a teacher working in German.
   */
  test('each locale gets its own 404, not the default locale’s', async ({ page }) => {
    await page.goto('/de/gibt-es-nicht');
    await expect(page.getByRole('heading', { name: /seite nicht gefunden/i })).toBeVisible();

    await page.goto('/en/nope');
    await expect(page.getByRole('heading', { name: /page not found/i })).toBeVisible();
  });

  test('never Next’s own English default page', async ({ page }) => {
    for (const path of ['/fr/ceci-nexiste-pas', '/de/gibt-es-nicht', '/it/classes']) {
      await page.goto(path);
      // Next's built-in 404 says exactly this, and ships no app chrome at all.
      await expect(page.getByText(/This page could not be found/i)).toHaveCount(0);
      await expect(page.locator('h1, h2, h3').first()).toBeVisible();
    }
  });

  /** A locale that is not ours is refused by the layout itself — the one case
   *  no catch-all can claim, because the layout is what raises it. */
  test('an unknown locale still lands on an Alppy page', async ({ page }) => {
    await page.goto('/it/classes');
    await expect(page.locator('h1, h2, h3').first()).toBeVisible();
  });
});
