import { expect, test } from '@playwright/test';

import { gotoStable } from './helpers';

/**
 * F3 — the points screen, and the one rule it exists to keep.
 *
 * "An ungraded copy shows a dash, never a zero. A term with two of five sheets
 * marked is not three failures." The screen says so at the top of its own file,
 * and the per-sheet cells obeyed it — the TOTAL column and the class average
 * did not.
 *
 * `GET /classes/{id}/points` returns, per pupil, an `earned` summed over the
 * sheets that have a grade and a `possible` summed over EVERY sheet the class
 * was given. That is deliberate on the API's side and `class_points_totals`
 * documents it: an unscanned copy is still paper the pupil was handed. What it
 * means is that the pair is not safe to divide — and this screen divided it.
 *
 * The cost, on the demo data: one corrected sheet worth 54 points across the
 * class and one sheet nobody had corrected worth 36 more. The class had scored
 * 11 of the 54 it actually sat and the screen reported 11/90 — 12% instead of
 * 20%, with an uncorrected sheet counted as a room full of zeros.
 *
 * The fixture's two sheets are worth 8 and 10 points a copy, and it leaves
 * three pupils ungraded on the second one on purpose.
 */
const SHEET_1_POINTS = 8;
const SHEET_2_POINTS = 10;

/** The pupil's name is a `th`, so the `td`s are sheet 1, sheet 2, TOTAL. */
const SHEET_1 = 0;
const SHEET_2 = 1;
const TOTAL = 2;

test('a copy nobody has corrected stays out of that pupil’s total', async ({ page }) => {
  await gotoStable(page, '/fr/results');

  const rows = page.locator('table tbody tr');
  await expect(rows.first()).toBeVisible();

  // A pupil with a dash in the second column sat exactly one of the two sheets.
  // It has to be one who actually scored something: a pupil who scored zero
  // reads as 0% however wide the denominator is, so they cannot tell the two
  // behaviours apart.
  const candidates = rows.filter({ hasText: '—' });
  let cells = null;
  for (let i = 0; i < (await candidates.count()); i++) {
    const row = candidates.nth(i).locator('td');
    const [sat, second] = [
      (await row.nth(SHEET_1).innerText()).trim(),
      (await row.nth(SHEET_2).innerText()).trim(),
    ];
    if (second === '—' && Number(sat) > 0) {
      cells = row;
      break;
    }
  }
  expect(cells, 'a pupil who sat one sheet and scored on it').not.toBeNull();

  // Their total IS that one sheet's percentage. Before the fix the sheet they
  // never sat sat in the denominator and dragged the total below it.
  const sat = (await cells!.nth(SHEET_1).innerText()).trim();
  const total = (await cells!.nth(TOTAL).innerText()).trim();
  expect(total).toBe(sat);
});

test('the class average counts only the paper that has been marked', async ({ page }) => {
  await gotoStable(page, '/fr/results');

  const card = page.locator('div').filter({ hasText: /Moyenne de la classe/i }).last();
  await expect(card).toBeVisible();

  // "earned / possible", on its own line beside the ring.
  const line = (await card.innerText()).split('\n').find((l) => l.includes('/'));
  expect(line, 'the average card shows earned / possible').toBeTruthy();
  const [earned, possible] = line!.split('/').map((s) => Number(s.replace(/[\s ]/g, '')));

  // What the denominator must be, counted off the screen itself: every graded
  // cell contributes its own sheet's worth, every dash contributes nothing.
  const gradedIn = async (column: number) =>
    (
      await page.locator(`table tbody tr td:nth-child(${column + 2})`).allInnerTexts()
    ).filter((t) => t.trim() !== '—' && t.trim() !== '').length;

  const expected =
    (await gradedIn(SHEET_1)) * SHEET_1_POINTS + (await gradedIn(SHEET_2)) * SHEET_2_POINTS;

  expect(possible).toBe(expected);
  expect(earned).toBeLessThanOrEqual(possible);
});
