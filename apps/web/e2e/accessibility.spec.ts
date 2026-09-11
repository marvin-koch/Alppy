import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

import { gotoStable, MATRIX_CLASS_ID, withDisplay } from './helpers';

/**
 * An automated accessibility pass, which the repo had none of (T25).
 *
 * What this is NOT: a claim that the product is accessible. Axe catches roughly
 * a third of WCAG issues and none of the ones that matter most here — whether
 * the mastery bands are distinguishable in greyscale, whether a screen reader
 * hears "faible" rather than a colour, whether the review screen is usable with
 * one hand on a phone. Those are the rules `DESIGN.md` numbers and a person has
 * to check.
 *
 * What it IS: the floor. A missing form label, an image with no alt text, a
 * control with no accessible name, an ARIA attribute pointing at an id that is
 * not there — the defects that are unambiguous, that nobody argues about, and
 * that no human reviewer reliably catches on the fortieth screen.
 *
 * Scoped to the rules that are objectively violations. `color-contrast` is
 * excluded deliberately and the reason is in the exclusion below.
 */

/** The screens a teacher cannot avoid. */
const SCREENS: readonly { name: string; path: string }[] = [
  { name: 'home', path: '/fr' },
  { name: 'classes', path: '/fr/classes' },
  { name: 'matrix', path: `/fr/classes/${MATRIX_CLASS_ID}` },
  { name: 'sheets', path: '/fr/sheets' },
  { name: 'scans', path: '/fr/scans' },
  { name: 'sources', path: '/fr/sources' },
  { name: 'timeline', path: '/fr/timeline' },
];

test.describe('every screen clears the automated accessibility floor', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  for (const screen of SCREENS) {
    test(`${screen.name} has no serious or critical violations`, async ({ page }) => {
      await gotoStable(page, screen.path);

      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        // Axe measures contrast against the computed background, and every
        // surface in this product is a CSS variable resolved per theme. It
        // reports the token name's fallback rather than what the teacher sees,
        // which produced noise rather than findings. Contrast is checked where
        // it is actually decided — `tokens.css` and the mastery ramp, whose
        // glyph colours are calibrated to a constant luminance precisely so the
        // bands survive a photocopier.
        .disableRules(['color-contrast'])
        .analyze();

      const serious = results.violations.filter((v) =>
        ['serious', 'critical'].includes(v.impact ?? ''),
      );

      // The message is the whole value: a violation count tells nobody what to
      // fix, and this report is read by whoever is mid-commit.
      const described = serious
        .map((v) => {
          const where = v.nodes
            .slice(0, 3)
            .map((n) => `        ${n.target.join(' ')}`)
            .join('\n');
          return `  [${v.impact}] ${v.id}: ${v.help}\n${where}\n        ${v.helpUrl}`;
        })
        .join('\n\n');

      expect(serious, `\n${described}\n`).toHaveLength(0);
    });
  }
});

test.describe('the things axe cannot see, asserted by hand', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('a mastery band is never colour alone', async ({ page }) => {
    // DC-colour-08. The photocopier is black and white and roughly one boy in
    // twelve is colour-blind, so every band carries colour AND a written label
    // AND a differing tint density. Axe has no rule for this and never will —
    // it is a product rule, not a WCAG one.
    await gotoStable(page, `/fr/classes/${MATRIX_CLASS_ID}`);

    const bands = page.locator('[data-band]');
    const count = await bands.count();
    expect(count, 'no mastery bands on the matrix to check').toBeGreaterThan(0);

    for (let index = 0; index < Math.min(count, 12); index += 1) {
      const band = bands.nth(index);
      const label = (await band.getAttribute('aria-label')) ?? (await band.innerText());
      expect(
        label.trim(),
        `a band with no words: a photocopy of this cell says nothing`,
      ).not.toBe('');
    }
  });

  test('every image carries alt text or is marked decorative', async ({ page }) => {
    await gotoStable(page, '/fr');
    const images = page.locator('img');
    for (let index = 0; index < (await images.count()); index += 1) {
      const image = images.nth(index);
      const alt = await image.getAttribute('alt');
      const hidden = await image.getAttribute('aria-hidden');
      expect(
        alt !== null || hidden === 'true',
        `an image with neither alt nor aria-hidden: ${await image.getAttribute('src')}`,
      ).toBe(true);
    }
  });
});

test.describe('the checker itself', () => {
  test('axe reports a violation that is really there', async ({ page }) => {
    // Every screen above passes, including with `color-contrast` enabled and
    // every impact level counted. That is good news and it is also the problem:
    // a suite of seven always-green assertions cannot tell "the product is
    // clean" from "the analyser never ran" — a bad import, a changed API, a
    // selector that matches nothing, and all seven keep passing.
    //
    // So plant one. An input with no label is the least ambiguous violation
    // there is, and axe must find it.
    await withDisplay(page, {});
    await gotoStable(page, '/fr');

    await page.evaluate(() => {
      const input = document.createElement('input');
      input.type = 'text';
      input.id = 'axe-self-check';
      document.body.append(input);
    });

    const results = await new AxeBuilder({ page }).include('#axe-self-check').analyze();

    expect(
      results.violations.map((v) => v.id),
      'axe found nothing wrong with an unlabelled input — it is not analysing',
    ).toContain('label');
  });
});
