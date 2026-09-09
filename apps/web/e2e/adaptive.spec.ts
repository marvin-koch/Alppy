import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * F4 regression cover for the two failures that only the browser could show:
 *
 * 1. **The export button never produced a PDF.** It POSTed `/adaptive/batch`,
 *    then polled `GET /jobs/<sheet-id>` — a 404, forever — because the client
 *    typed the batch response as a `JobOut` when the server returns a
 *    `SheetOut`. `tsc` could not see it (`apiRequest<T>` is an unchecked
 *    assertion), the mock agreed with the wrong client, and no test clicked the
 *    button. So this file clicks the button and checks both what appears on
 *    screen and which calls the mock actually served.
 * 2. **"Approve all" approved nothing.** It set React state and issued no
 *    request, so `approved_at` stayed NULL and the gate it appeared to satisfy
 *    was never touched.
 *
 * Plus the two display-state defects found on this screen: the accent approve
 * button was unreadable in three of four themes, and every card lost its edge
 * in high contrast.
 */

const ADAPTIVE = '/fr/adaptive';

/** Relative luminance per WCAG 2.1, from an `rgb()`/`rgba()` string. */
function luminance(colour: string): number {
  const [r, g, b] = (colour.match(/\d+(\.\d+)?/g) ?? ['0', '0', '0']).slice(0, 3).map(Number);
  const channel = (value: number) => {
    const v = (value ?? 0) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r as number) + 0.7152 * channel(g as number) + 0.0722 * channel(b as number);
}

function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/** Everything the in-process mock API served. See `mock/handlers.ts`. */
async function mockCalls(page: import('@playwright/test').Page): Promise<string[]> {
  return page.evaluate(() => (window as { __alppyMockCalls?: string[] }).__alppyMockCalls ?? []);
}

/** The id the batch call created, read back out of the render call it triggered. */
function sheetIdOf(calls: string[]): string {
  const render = calls.find((c) => /^POST \/adaptive\/batch\/[^/]+\/render$/.test(c)) ?? '';
  return render.split('/')[3] ?? '';
}

async function prepare(page: import('@playwright/test').Page): Promise<void> {
  await gotoStable(page, ADAPTIVE);
  await page.getByRole('button', { name: /Préparer/i }).click();
  // Planning is a job now — the model calls run in the worker — so this waits
  // through the poll rather than through one request. The heading is the first
  // thing that can only exist once the proposal has actually been read back.
  await page
    .getByRole('heading', { name: /Compétences ciblées/i })
    .waitFor({ timeout: 20_000 });
}

test.describe('the adaptive batch export', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('produces a downloadable PDF and its answer key', async ({ page }) => {
    await prepare(page);

    // Generated items must be approved first — the button says so and the
    // server refuses too.
    await page.getByRole('button', { name: /Tout approuver/i }).click();
    await expect(page.getByText(/peuvent maintenant être imprimés/i)).toBeVisible();

    await page.getByRole('button', { name: /Exporter le lot PDF/i }).click();

    // The whole point: a link to a real document, not a spinner that never ends.
    await expect(page.getByRole('link', { name: /Télécharger les fiches/i })).toBeVisible({
      timeout: 15_000,
    });
    // Always two sheets (DESIGN.md §9).
    await expect(page.getByRole('link', { name: /Télécharger le corrigé/i })).toBeVisible();

    // The render call is what returns the job. Creating the batch does not, and
    // the client used to treat the new sheet's id AS a job id and poll a 404.
    const calls = await mockCalls(page);
    expect(
      calls.filter((c) => /^POST \/adaptive\/batch\/[^/]+\/render$/.test(c)),
      'the render endpoint must be called',
    ).toHaveLength(1);
    const polled = calls.filter((c) => c.startsWith('GET /jobs/')).map((c) => c.slice(10));
    expect(polled.length).toBeGreaterThan(0);
    expect(polled, 'a sheet id must never be polled as a job id').not.toContain(sheetIdOf(calls));
  });

  test('approving writes to the server rather than flipping a local flag', async ({ page }) => {
    await prepare(page);
    await page.getByRole('button', { name: /Tout approuver/i }).click();
    await expect(page.getByText(/peuvent maintenant être imprimés/i)).toBeVisible();

    const calls = await mockCalls(page);
    expect(
      calls.filter((c) => c === 'POST /adaptive/approve'),
      'approval must be a call, not a checkbox',
    ).toHaveLength(1);
  });

  test('the export button is blocked while generated items are unapproved', async ({ page }) => {
    await prepare(page);
    await expect(page.getByRole('button', { name: /Exporter le lot PDF/i })).toBeDisabled();
    await page.getByRole('button', { name: /Tout approuver/i }).click();
    await expect(page.getByRole('button', { name: /Exporter le lot PDF/i })).toBeEnabled();
  });
});

test.describe('reviewing generated items', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('the teacher can read every exercise before approving it', async ({ page }) => {
    await prepare(page);
    // The approval step is meaningless if the items are never shown: the screen
    // used to offer a count and a badge and nothing else.
    await page.getByRole('button', { name: /Afficher les \d+ exercices/i }).first().click();
    const items = page.getByTestId('adaptive-item');
    await expect(items.first()).toBeVisible();
    // A statement, not just a title.
    await expect(items.first()).not.toBeEmpty();
  });

  test('a generated item can be regenerated in place', async ({ page }) => {
    await prepare(page);
    await page.getByRole('button', { name: /Afficher les \d+ exercices/i }).first().click();

    const generated = page.getByTestId('adaptive-item').filter({ has: page.locator('[data-ai-generated]') });
    const before = await generated.count();
    if (before === 0) test.skip(true, 'this fixture student has no generated item');

    const original = (await generated.first().innerText()).trim();
    await generated.first().getByRole('button', { name: /Régénérer/i }).click();

    // Replaces, never appends.
    await expect
      .poll(async () => (await generated.first().innerText()).trim(), { timeout: 10_000 })
      .not.toBe(original);
    await expect(generated).toHaveCount(before);
  });

  test('a discarded item leaves the sheet', async ({ page }) => {
    await prepare(page);
    await page.getByRole('button', { name: /Afficher les \d+ exercices/i }).first().click();

    const generated = page.getByTestId('adaptive-item').filter({ has: page.locator('[data-ai-generated]') });
    const before = await generated.count();
    if (before === 0) test.skip(true, 'this fixture student has no generated item');

    await generated.first().getByRole('button', { name: /Écarter/i }).click();
    await expect(generated).toHaveCount(before - 1);
  });
});

test.describe('the adaptive screen in every display state', () => {
  const STATES = [
    { name: 'light', display: { theme: 'light' } as const },
    { name: 'dark', display: { theme: 'dark' } as const },
    { name: 'contrast', display: { contrast: 'high' } as const },
    { name: 'dark-contrast', display: { theme: 'dark', contrast: 'high' } as const },
  ];

  for (const state of STATES) {
    test(`the accent approve button stays readable in ${state.name}`, async ({ page }) => {
      await withDisplay(page, state.display);
      await prepare(page);

      const button = page.getByRole('button', { name: /Tout approuver/i });
      const { colour, background } = await button.evaluate((el) => {
        const style = getComputedStyle(el);
        return { colour: style.color, background: style.backgroundColor };
      });
      // It is the single sanctioned accent action in the product, and it used
      // to sit at 1.65:1 in dark + high contrast.
      expect(contrast(colour, background), `${state.name} accent button`).toBeGreaterThanOrEqual(4.5);
    });

    test(`a card keeps a visible edge in ${state.name}`, async ({ page }) => {
      await withDisplay(page, state.display);
      await gotoStable(page, ADAPTIVE);

      const edged = await page.locator('.ard-card').first().evaluate((el) => {
        const style = getComputedStyle(el);
        const body = getComputedStyle(document.body);
        return {
          shadow: style.boxShadow,
          border: parseFloat(style.borderTopWidth || '0'),
          card: style.backgroundColor,
          canvas: body.backgroundColor,
        };
      });
      // `--shadow-ambient: none` made `box-shadow: 0 2px 0 0 <edge>, none`
      // invalid, so the browser dropped the whole declaration and the card
      // became invisible against the canvas — in the one mode a low-vision
      // teacher reaches for.
      const separated =
        edged.shadow !== 'none' || edged.border > 0 || contrast(edged.card, edged.canvas) > 1.05;
      expect(separated, `${state.name}: card has no edge and no tint`).toBe(true);
    });
  }
});
