import { expect, test } from '@playwright/test';

import { gotoMatrix, gotoStable, matrixPath, withDisplay } from './helpers';

/**
 * The user asked for the product to work on a phone and a PC. These are the
 * assertions that actually hold that: a passing desktop suite says nothing
 * about a 390px screen.
 */

test('the page never scrolls sideways', async ({ page }) => {
  await withDisplay(page, {});
  for (const path of [
    '/fr',
    '/fr/classes',
    // The matrix route, not just the class index. This list stopped at
    // `/fr/classes` — a page with no matrix on it — so the one assertion
    // guarding "the matrix must never push the document sideways" never
    // actually loaded a matrix.
    matrixPath('fr'),
    '/fr/sources',
    '/fr/adaptive',
    '/fr/settings',
  ]) {
    await gotoStable(page, path);
    // The mastery matrix is wide by nature. It must scroll inside its OWN
    // container, never by pushing the document sideways.
    //
    // The predicate is "can the page actually be panned", not
    // `documentElement.scrollWidth`: that reports the union of descendant
    // bounding boxes and counts content an ancestor already clips, so on the
    // matrix route it claims ~300px of overflow for a page that cannot move a
    // pixel. Try to scroll, then look.
    const panned = await page.evaluate(() => {
      window.scrollTo(5000, 0);
      const x = window.scrollX;
      window.scrollTo(0, 0);
      return x;
    });
    expect(panned, `${path} can be scrolled sideways by ${panned}px`).toBe(0);
  }
});

test('the matrix scrolls in its own container with a sticky name column', async ({
  page,
}, testInfo) => {
  await withDisplay(page, {});
  await gotoMatrix(page, 'fr');
  // No skip: this used to look for `[data-matrix-scroll]` on the class index,
  // where nothing rendered it, so the test passed as a skip forever.
  const scroller = page.locator('[data-matrix-scroll]').first();
  await expect(scroller).toBeVisible();
  expect(await scroller.evaluate((el) => getComputedStyle(el).overflowX)).toBe('auto');

  // The sticky name column paints its own background, or the scrolled cells
  // slide under the names.
  const rowHeader = page.locator('tbody tr th').first();
  const background = await rowHeader.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(background).not.toBe('rgba(0, 0, 0, 0)');

  if (testInfo.project.name !== 'phone') return;

  // On a phone the grid is genuinely wider than the screen. That width must be
  // absorbed by the scroller and NOT reach the document: `documentElement`
  // reported 396px of overflow on this route while the guard above only ever
  // visited the class index, which has no matrix on it.
  const measured = await page.evaluate(() => {
    const el = document.querySelector('[data-matrix-scroll]');
    window.scrollTo(5000, 0);
    const panned = window.scrollX;
    window.scrollTo(0, 0);
    return { scroller: el ? el.scrollWidth - el.clientWidth : -1, panned };
  });
  expect(measured.scroller, 'the matrix scrolls inside its own box').toBeGreaterThan(0);
  expect(measured.panned, 'and the page itself does not pan sideways').toBe(0);
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

test('a real wheel cannot pan the page sideways', async ({ page }, testInfo) => {
  await withDisplay(page, {});
  await gotoMatrix(page, 'fr');

  // The guard above uses `window.scrollTo`, which is a PROGRAMMATIC scroll and
  // succeeds even against `overflow-x: hidden` — so it could not see the
  // document panning 233px in a non-touch window while passing on the phone
  // project. A wheel is what a user actually does.
  const heading = await page.locator('h1').first().boundingBox();
  if (!heading) throw new Error('no heading to aim the wheel at');
  await page.mouse.move(heading.x + 5, heading.y + 5);
  await page.mouse.wheel(400, 0);
  await page.waitForTimeout(300);

  const panned = await page.evaluate(() => window.scrollX);
  expect(panned, `the wheel panned the document ${panned}px`).toBe(0);

  // ...and where the grid is genuinely wider than the screen it must still
  // scroll inside its own box, or we have "fixed" the overflow by making the
  // grid unreadable. At 1440 it fits, so there is nothing to assert there.
  if (testInfo.project.name !== 'phone') return;
  const scroller = page.locator('[data-matrix-scroll]').first();
  expect(await scroller.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeGreaterThan(0);
});
