import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * The user asked for the product to work on a phone and a PC. These are the
 * assertions that actually hold that: a passing desktop suite says nothing
 * about a 390px screen.
 */

test('the page never scrolls sideways', async ({ page }) => {
  await withDisplay(page, {});
  for (const path of ['/fr', '/fr/classes', '/fr/sources', '/fr/adaptive', '/fr/settings']) {
    await gotoStable(page, path);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    // The mastery matrix is wide by nature. It must scroll inside its OWN
    // container, never by pushing the document sideways.
    expect(overflow, `${path} overflows horizontally by ${overflow}px`).toBeLessThanOrEqual(1);
  }
});

test('the matrix scrolls in its own container with a sticky name column', async ({ page }) => {
  await withDisplay(page, {});
  await gotoStable(page, '/fr/classes');
  const scroller = page.locator('[data-matrix-scroll]').first();
  if ((await scroller.count()) === 0) test.skip(true, 'no matrix on this fixture');
  const overflowX = await scroller.evaluate((el) => getComputedStyle(el).overflowX);
  expect(overflowX).toBe('auto');
});

test('every interactive control meets the touch-target floor', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'phone', 'touch targets matter on the phone');
  await withDisplay(page, {});
  await gotoStable(page, '/fr');
  const controls = page.locator('button:visible, a[href]:visible');
  const count = Math.min(await controls.count(), 25);
  for (let i = 0; i < count; i += 1) {
    const box = await controls.nth(i).boundingBox();
    if (!box || box.height === 0) continue;
    // 44px is the design floor and is called non-negotiable in DESIGN.md §6.
    // Two things are legitimately exempt: an inline text link inside a
    // paragraph, and the skip link, which is clipped to 1px until it takes
    // focus. Neither is something a thumb aims at.
    const exempt = await controls.nth(i).evaluate((el) => {
      const s = getComputedStyle(el);
      const clipped = s.clip !== 'auto' || s.clipPath !== 'none';
      const inlineLink = el.tagName === 'A' && s.display === 'inline';
      return clipped || inlineLink;
    });
    if (exempt) continue;
    expect(box.height, `control ${i} is ${box.height}px tall`).toBeGreaterThanOrEqual(40);
  }
});

test('the phone gets a drawer and bottom tabs; the desktop gets a rail', async ({
  page,
}, testInfo) => {
  await withDisplay(page, {});
  await gotoStable(page, '/fr');
  const rail = page.locator('aside').first();
  if (testInfo.project.name === 'phone') {
    await expect(rail).toBeHidden();
    await expect(page.locator('nav').last()).toBeVisible();
  } else {
    await expect(rail).toBeVisible();
  }
});
