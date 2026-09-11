import type { Page } from '@playwright/test';

export const LOCALES = ['fr', 'de', 'en'] as const;

/**
 * The class whose mastery matrix the suite screenshots.
 *
 * `/classes` is the class *index* — two cards and no grid. Every test named
 * "matrix renders in ..." pointed there, so eighteen baselines were pictures of
 * the wrong page and the matrix had no visual-regression coverage at all. It is
 * also why the sideways-scroll guard never saw the matrix overflow the document
 * on a phone. This id comes from `lib/api/mock/fixtures.ts` (`id(20)`, class 7B).
 */
export const MATRIX_CLASS_ID = '00000000-0000-4000-8000-000000000020';

/** The route the mastery matrix actually lives on. */
export function matrixPath(locale: string): string {
  return `/${locale}/classes/${MATRIX_CLASS_ID}`;
}

/** The four display switches, as they are actually persisted. */
export interface Display {
  theme?: 'light' | 'dark';
  contrast?: 'high';
  motion?: 'off';
  calm?: 'on';
}

/**
 * Seed the display preferences *before* the first paint, the same way the app
 * does. Setting them after load would screenshot the light palette mid-swap.
 */
export async function withDisplay(page: Page, display: Display): Promise<void> {
  await page.addInitScript((prefs) => {
    window.localStorage.setItem('alppy.mock', '1');
    // Seed ONLY on the first load. addInitScript runs again on every reload, so
    // writing unconditionally would clobber whatever the app had just saved --
    // which made the "theme persists across a reload" test fail against a
    // perfectly correct app. Each test gets a fresh context, so "absent" really
    // does mean "first load here".
    if (window.localStorage.getItem('alppy.display') === null) {
      window.localStorage.setItem('alppy.display', JSON.stringify(prefs));
    }
  }, display);
}

export async function gotoStable(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await page.waitForLoadState('networkidle');
  // Skeletons resolve into content; wait for the heading rather than a timeout.
  await page.locator('h1').first().waitFor({ state: 'visible' });
}

/** Navigate to the matrix and wait for the grid itself, not just the heading. */
export async function gotoMatrix(page: Page, locale = 'fr'): Promise<void> {
  await gotoStable(page, matrixPath(locale));
  await page.locator('table tbody tr td button').first().waitFor({ state: 'visible' });
}

/** The name a screenshot is filed under. */
export function shot(name: string, ...parts: string[]): string {
  return [name, ...parts].filter(Boolean).join('-') + '.png';
}

/**
 * Clear the review screen's default filter.
 *
 * A pile now OPENS on the items that need a human — low confidence and multiple
 * marks — because least-confident-first only ordered within a page and a 28-page
 * pile used to open on page 1's settled items (G12). Anything already settled,
 * including a written answer the model read confidently, is therefore hidden until
 * the filter is cleared.
 *
 * A no-op when the pile has nothing uncertain in it, so a spec can call it
 * unconditionally.
 */
export async function showEveryItem(page: Page): Promise<void> {
  const clear = page.getByRole('button', { name: /tout afficher|effacer les filtres/i }).first();
  if (await clear.count()) await clear.click();
}
