import { expect, test } from '@playwright/test';

import { shot, withDisplay } from './helpers';

/**
 * The component workbench (F26).
 *
 * One screenshot per display state. The value is not the picture on its own —
 * it is that a token change now shows up as a diff on ONE page carrying every
 * primitive, instead of being noticed on whichever screen a reviewer happened
 * to open. The band ramp, the four button variants and all four screen states
 * are on it, and none of them had a home before.
 */
const STATES = [
  { name: 'light', display: { theme: 'light' as const } },
  { name: 'dark', display: { theme: 'dark' as const } },
  { name: 'contrast', display: { theme: 'light' as const, contrast: 'high' as const } },
];

for (const state of STATES) {
  test(`the gallery renders in ${state.name}`, async ({ page }) => {
    await withDisplay(page, state.display);
    await page.goto('/fr/_gallery');
    await page.locator('[data-gallery]').waitFor();

    // Every rule this page exists to make visible, asserted rather than only
    // photographed: a band without its label is the failure mode the required
    // prop exists to prevent (DC-colour-08).
    const bands = page.locator('[data-band]');
    expect(await bands.count()).toBeGreaterThan(0);
    for (const band of await bands.all()) {
      expect((await band.innerText()).trim().length).toBeGreaterThan(0);
    }

    await expect(page).toHaveScreenshot(shot('gallery', state.name), { fullPage: true });
  });
}
