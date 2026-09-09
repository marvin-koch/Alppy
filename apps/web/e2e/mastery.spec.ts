import { expect, test } from '@playwright/test';

import { gotoMatrix, gotoStable, matrixPath, withDisplay } from './helpers';

/**
 * F3 — the mastery matrix and the student profile.
 *
 * Every test here pins a behaviour that was broken and is now fixed. The suite
 * previously had no coverage of this screen at all: the tests named "matrix
 * renders in ..." pointed at the class index.
 */

test('a never-assessed cell shows no number, and a zero score does', async ({ page }) => {
  // docs/mastery-model.md §2, in bold: "Not yet seen" is a band, not a zero.
  // Both used to render an identical bold 0, separated only by tint and a 12px
  // glyph — and the accessible name said "Pas encore vu · 0 %" in one breath.
  await withDisplay(page, {});
  await gotoMatrix(page, 'fr');

  const none = page.locator('button[data-band="none"]').first();
  await expect(none).toBeVisible();
  await expect(none).toHaveText(/^\s*$/);
  await expect(none).toHaveAttribute('aria-label', /Pas encore vu/);
  expect(await none.getAttribute('aria-label')).not.toMatch(/\d\s*%/);

  // A cell that was assessed still shows its number.
  const assessed = page.locator('button[data-band="fading"], button[data-band="ok"]').first();
  await expect(assessed).toHaveText(/\d/);
});

test('arrow keys move between cells and Enter opens the drill-down', async ({ page }) => {
  await withDisplay(page, {});
  await gotoMatrix(page, 'fr');

  const cells = page.locator('tbody td button');
  await cells.first().focus();
  const start = await cells.first().getAttribute('aria-label');

  const activeLabel = () => page.evaluate(() => document.activeElement?.getAttribute('aria-label'));

  await page.keyboard.press('ArrowRight');
  const right = await activeLabel();
  expect(right).not.toBe(start);

  await page.keyboard.press('ArrowDown');
  expect(await activeLabel()).not.toBe(right);

  await page.keyboard.press('ArrowUp');
  await page.keyboard.press('ArrowLeft');
  expect(await activeLabel()).toBe(start);

  // The grid is ONE tab stop, not one per cell: a class of 30 x 25 is 750.
  const tabbable = await page.locator('tbody td button[tabindex="0"]').count();
  expect(tabbable).toBe(1);

  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog')).toBeVisible();
});

test('a cell drills down to its attempts, with links back to sheet and scan', async ({ page }) => {
  await withDisplay(page, {});
  await gotoMatrix(page, 'fr');

  await page.locator('tbody td button').first().click();
  const panel = page.getByRole('dialog');
  await expect(panel).toBeVisible();

  // The competency that was clicked is named, not thrown away.
  await expect(panel.getByText(/MSN \d+/).first()).toBeVisible();
  // Individual answers, each with an outcome word — never colour alone.
  const rows = panel.locator('[data-outcome]');
  expect(await rows.count()).toBeGreaterThan(0);
  await expect(rows.first()).toHaveText(/Juste|Faux/);
  // Provenance: back to the paper it came from.
  await expect(panel.getByRole('link', { name: /Fiche/ }).first()).toBeVisible();
  await expect(panel.getByRole('link', { name: /copie scannée/ }).first()).toBeVisible();
});

test('the roster name reaches the profile without going through a cell', async ({ page }) => {
  // A class with nothing assessed yet has no cells at all, so a coloured cell
  // cannot be the only route to a student.
  await withDisplay(page, {});
  await gotoMatrix(page, 'fr');
  await page.locator('tbody tr th a').first().click();
  await expect(page).toHaveURL(/\/classes\/[^/]+\/students\/[^/]+$/);
  await expect(page.locator('h1')).toBeVisible();
});

test('the programme tree narrows the columns and the sort reorders the rows', async ({
  page,
}) => {
  // The tree IS the filter here. This used to drive a pair of chained selects
  // that sat beside it doing the same job; the duplication went, the behaviour
  // did not, so the assertion moved rather than being deleted.
  await withDisplay(page, {});
  await gotoMatrix(page, 'fr');

  const columns = () => page.locator('thead th').count();
  const firstRowName = () => page.locator('tbody tr th').first().innerText();

  const before = await columns();
  const firstBefore = await firstRowName();

  // A Theme is a `li > button`; a Competence heading is a `header > button`,
  // and both can contain the word "Fractions".
  await page.locator('li > button').filter({ hasText: 'Fractions' }).first().click();
  await expect.poll(columns).toBeLessThan(before);

  await page.getByRole('button', { name: 'Tout afficher' }).click();
  await expect.poll(columns).toBe(before);

  await page.getByLabel('Trier').selectOption({ label: 'Les plus fragiles d\'abord' });
  await expect.poll(firstRowName).not.toBe(firstBefore);
});

test('the legend carries the tint, the glyph and the word', async ({ page }) => {
  // Colour is never the only channel, and a legend of identical grey text chips
  // maps nothing onto the grid it is supposed to explain.
  await withDisplay(page, {});
  await gotoMatrix(page, 'fr');

  const swatches = page.locator('[data-band]').filter({ hasText: /Acquis|À revoir|Fragile/ });
  expect(await swatches.count()).toBeGreaterThanOrEqual(3);

  const backgrounds = await page
    .locator('li > span[data-band]')
    .evaluateAll((els) => els.map((el) => getComputedStyle(el).backgroundColor));
  expect(new Set(backgrounds).size).toBe(backgrounds.length); // five different tints
  // Each swatch carries the glyph too.
  expect(await page.locator('li > span[data-band] svg').count()).toBe(backgrounds.length);
});

test('the bands stay legible in every display state', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'phone', 'sampled once, on the desktop grid');
  // The band tokens were defined on :root only. In dark, the ink on an `ok`
  // cell fell to 1.03:1 and the number vanished; high contrast changed the
  // page chrome and left every data cell untouched.
  const BANDS = ['solid', 'ok', 'weak', 'fading', 'none'];

  /** Runs in the page: background/ink luminance and their contrast, per band. */
  const readBands = (bands: string[]) => {
    // Two notations reach us: `rgb(r, g, b)` with 0-255 channels, and
    // `color(srgb r g b)` with 0-1 channels, which is what a `color-mix()` tint
    // computes to. Treating the second as 0-255 reports every light-theme cell
    // as near-black and turns a passing contrast into a failing one.
    const luminance = (value: string) => {
      const raw = (value.match(/[\d.]+/g) ?? ['0', '0', '0']).map(Number).slice(0, 3);
      const [r, g, b] = value.startsWith('color(') ? raw.map((v) => v * 255) : raw;
      const ch = (v: number) => {
        const s = (v ?? 0) / 255;
        return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * ch(r as number) + 0.7152 * ch(g as number) + 0.0722 * ch(b as number);
    };
    return bands.flatMap((band) => {
      const el = document.querySelector(`button[data-band="${band}"]`);
      if (!el) return [];
      const style = getComputedStyle(el);
      const bg = luminance(style.backgroundColor);
      const ink = luminance(style.color);
      const [hi, lo] = bg > ink ? [bg, ink] : [ink, bg];
      return [{ band, bg, contrast: (hi + 0.05) / (lo + 0.05) }];
    });
  };

  for (const display of [{}, { theme: 'dark' as const }, { contrast: 'high' as const }]) {
    const name = JSON.stringify(display);
    const context = await page.context().browser()!.newContext();
    const fresh = await context.newPage();
    await withDisplay(fresh, display);
    await fresh.goto(matrixPath('fr'));
    await fresh.locator('tbody td button').first().waitFor({ state: 'visible' });

    const readings = await fresh.evaluate(readBands, BANDS);

    expect(readings.length, `${name}: all five bands present`).toBe(5);
    for (const reading of readings) {
      expect(reading.contrast, `${name}: ${reading.band} ink on tint`).toBeGreaterThanOrEqual(4.4);
    }
    // Strictly monotonic in greyscale, so the ramp survives a photocopy or a
    // reader who sees no colour. Direction differs by theme; ordering does not.
    const ys = readings.map((r) => r.bg);
    const up = ys.every((y, i) => i === 0 || y > (ys[i - 1] as number));
    const down = ys.every((y, i) => i === 0 || y < (ys[i - 1] as number));
    expect(up || down, `${name}: greyscale ramp is monotonic (${ys.join(', ')})`).toBe(true);

    await context.close();
  }
});

test('a student with no attempts is not shown as a zero', async ({ page }) => {
  await withDisplay(page, {});
  // Class 9A in the fixtures has students but nothing assessed.
  await gotoStable(page, '/fr/classes/00000000-0000-4000-8000-000000000021');
  await expect(page.getByText('Aucune donnée de maîtrise')).toBeVisible();
  // The legend is still on the page, so the vocabulary is always available.
  await expect(page.getByText('Légende')).toBeVisible();
});

test('the profile shows the trend and the sheets behind it', async ({ page }) => {
  await withDisplay(page, {});
  await gotoStable(page, `${matrixPath('fr')}/students/00000000-0000-4000-8000-000000000100`);

  // The ring carries a unit, not a bare integer.
  await expect(page.getByText(/%/).first()).toBeVisible();
  // A curve, which never rendered because every history had a single point.
  await expect(page.getByText('Évolution')).toBeVisible();
  // The sheets sat, each a route back to the paper.
  await expect(page.getByText('Historique')).toBeVisible();
  await expect(page.getByRole('link', { name: /Fractions/ }).first()).toBeVisible();
});
