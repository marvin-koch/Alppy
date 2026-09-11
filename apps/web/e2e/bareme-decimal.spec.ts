import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * A decimal barème arrives as the number the teacher typed.
 *
 * This has to run in a real browser, and a Vitest test cannot replace it. The
 * bug was the HTML value-sanitisation algorithm: `1.` is not a valid
 * floating-point number, so a `type="number"` input reports its value as the
 * empty string mid-typing, `Number('')` is 0, React writes that 0 back into the
 * field, and the next keystroke lands in a box that was silently reset — `1.5`
 * became `5`. jsdom does not implement that step for typed input (it drops the
 * `.` keystroke instead of producing an empty value), so under Vitest the
 * pre-fix field happened to survive `1.5` and the bug was invisible. The comma
 * broke under both.
 *
 * So: the unit test in `PointsSelect.test.tsx` pins the parse and the fallback,
 * and this pins the thing only a browser can answer.
 */
test.describe('a typed barème', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  async function customPointsField(page: import('@playwright/test').Page) {
    await gotoStable(page, '/fr/sheets/new');
    await page.getByLabel(/document source/i).selectOption({ index: 1 });
    await expect(page.getByRole('heading', { name: /dans le document/i })).toBeVisible();
    await page.getByRole('checkbox').first().check();

    const bareme = page.locator('[data-bareme]');
    // "Personnalisé" is what reveals the typed field; the presets are a select.
    await bareme.getByLabel(/points par bonne réponse/i).selectOption({ label: 'Personnalisé' });
    return bareme.getByLabel(/^Points \(jusqu/i);
  }

  test('1.5 stays 1.5, and the sheet total agrees', async ({ page }) => {
    const field = await customPointsField(page);

    await field.fill('');
    // Character by character: filling the whole string at once never produces
    // the intermediate `1.` that broke it.
    await field.pressSequentially('1.5');

    await expect(field).toHaveValue('1.5');
    // The number the DRAFT holds, not just the text in the box — one item at
    // 1.5 points is a sheet worth 1.5.
    //
    // Either separator is accepted here on purpose. This total goes through a
    // catalogue message (`{points, number}`), which next-intl formats with the
    // app locale `fr` and so writes a comma, while `lib/format.ts` formats with
    // `fr-CH` and writes a period. That inconsistency is real and is not what
    // this test is about; pinning one separator here would make this test fail
    // for whoever settles that question.
    await expect(page.locator('[data-bareme]')).toContainText(/1[.,]5 point/i);
  });

  test('a typed comma is read as a decimal point', async ({ page }) => {
    const field = await customPointsField(page);

    await field.fill('');
    await field.pressSequentially('2,5');

    // The comma survives in the box, and still reaches the draft as 2.5.
    await expect(field).toHaveValue('2,5');
    await expect(page.locator('[data-bareme]')).toContainText(/2[.,]5 point/i);
  });
});
