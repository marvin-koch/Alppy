import type { Page } from '@playwright/test';

export const LOCALES = ['fr', 'de', 'en'] as const;

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

/** The name a screenshot is filed under. */
export function shot(name: string, ...parts: string[]): string {
  return [name, ...parts].filter(Boolean).join('-') + '.png';
}
