import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * The document-first builder.
 *
 * These assert the four things the rework exists for, and one it must not
 * break: picking a document and a chapter, ticking exercises, keeping those
 * ticks across a filter change, writing an exercise by hand, and reaching the
 * preview only when asked for it.
 *
 * Where it matters they read the mock's call log rather than the rendered DOM.
 * A filter chip that changes a React state and never reaches the API looks
 * identical on screen and is broken — that is the difference this seam exists
 * to catch.
 */
test.describe('sheet builder', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  async function openDocument(page: import('@playwright/test').Page) {
    await gotoStable(page, '/fr/sheets/new');
    await page
      .getByLabel(/document source/i)
      .selectOption({ index: 1 });
    await expect(page.getByRole('heading', { name: /dans le document/i })).toBeVisible();
  }

  test('a document and its chapter drive the list', async ({ page }) => {
    await openDocument(page);

    // The book's own chapter is the primary control, and it names a page range
    // the teacher can check against the paper on their desk.
    await expect(page.getByText(/les fractions/i).first()).toBeVisible();
    await expect(page.getByText(/p\. 78–112/)).toBeVisible();

    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls.some((c) => c.includes('/sections'))).toBe(true);
    expect(calls.some((c) => c.includes('/exercises'))).toBe(true);
  });

  test('ticks survive a filter change', async ({ page }) => {
    await openDocument(page);

    const first = page.getByRole('checkbox').first();
    await first.check();
    await expect(page.getByText(/1 coché en tout/)).toBeVisible();
    await expect(page.getByRole('heading', { name: /sur la feuille/i })).toBeVisible();

    // Narrowing the list must not drop what is already on the sheet: the
    // selection lives in the draft, never in the visible page of rows.
    await page.getByRole('button', { name: /^vrai ou faux/i }).click();
    await expect(page.getByText(/1 coché en tout/)).toBeVisible();

    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls.some((c) => c.includes('type=true_false'))).toBe(true);
  });

  test('paging asks the API for the next page rather than slicing on the client', async ({
    page,
  }) => {
    await openDocument(page);
    // The fixture chapter holds more than one page on purpose: a skipped
    // assertion here would let a broken paginator through unnoticed.
    await page.getByRole('button', { name: /^suivant$/i }).click();

    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls.some((c) => c.includes('offset=20'))).toBe(true);
  });

  test('the preview is closed until it is asked for', async ({ page }) => {
    await openDocument(page);
    await expect(page.getByRole('heading', { name: /^aperçu$/i })).toBeHidden();

    // With it closed, the page budget still has to be visible — otherwise
    // nothing stops a teacher ticking forty exercises onto a 16-per-page grid.
    await page.getByRole('checkbox').first().check();
    // In the composer, not the phone summary bar — this is the assertion that
    // the budget is reachable with the preview shut.
    await expect(page.getByRole('tabpanel').getByText(/1 page A4/)).toBeVisible();

    await page.getByRole('button', { name: /afficher l'aperçu/i }).click();
    await expect(page.getByRole('heading', { name: /^aperçu$/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /masquer l'aperçu/i })).toBeVisible();
  });

  test('a hand-written true/false exercise reaches the sheet', async ({ page }) => {
    await openDocument(page);
    await page.getByRole('button', { name: /ajouter un exercice/i }).click();

    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', { name: /vrai ou faux/i }).click();
    await dialog
      .getByRole('textbox', { name: /énoncé/i })
      .fill('6/9 et 2/3 sont deux écritures de la même fraction.');
    await dialog.getByRole('button', { name: /ajouter à la feuille/i }).click();

    // It wears the neutral chip, never the mandarin: the accent means "a model
    // wrote this" and spending it on a teacher's own sentence would cost it
    // that meaning everywhere else in the product.
    await expect(page.getByText(/écrit par vous/i)).toBeVisible();
    await expect(page.getByText(/6\/9 et 2\/3/)).toBeVisible();

    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls).toContain('POST /exercises');
  });

  test('deleting the correct answer clears the key rather than moving it', async ({ page }) => {
    await openDocument(page);
    await page.getByRole('button', { name: /ajouter un exercice/i }).click();

    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', { name: /choix multiple/i }).click();
    await dialog.getByRole('textbox', { name: /énoncé/i }).fill('Quelle fraction vaut 0,4 ?');
    await dialog.getByRole('textbox', { name: /réponses a/i }).fill('1/4');
    await dialog.getByRole('textbox', { name: /réponses b/i }).fill('2/5');
    await dialog.getByRole('button', { name: /ajouter une réponse/i }).click();
    await dialog.getByRole('textbox', { name: /réponses c/i }).fill('4/10');

    // Mark B correct, then delete B. The key is now genuinely unknown, and the
    // old behaviour shifted the index down so whatever slid into that slot
    // became "correct" — silently, on the value the answer sheet prints and the
    // scan pipeline grades against.
    await dialog.getByRole('radio', { name: /marquer b comme correcte/i }).check();
    await dialog.getByRole('button', { name: /supprimer la réponse b/i }).click();

    await dialog.getByRole('button', { name: /ajouter à la feuille/i }).click();
    await expect(dialog.getByText(/indiquez la réponse correcte/i)).toBeVisible();
    await expect(dialog).toBeVisible();

    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls, 'nothing may be created with an unknown key').not.toContain('POST /exercises');
  });

  test('an unread chapter offers to be read', async ({ page }) => {
    await openDocument(page);
    await page.getByRole('button', { name: /changer de chapitre/i }).click();

    // Import maps every chapter but only transcribes as many as its budget
    // allows; the rest are read here, on demand.
    await expect(page.getByText(/indexé, pas encore lu/i).first()).toBeVisible();
    await page.getByRole('button', { name: /^extraire$/i }).first().click();

    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls.some((c) => c.includes('/extract'))).toBe(true);
  });

  test('a phone acknowledges a tick without a scroll', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'phone', 'phone only');
    await openDocument(page);

    // The composer sits below a twenty-row list on a phone, so without this bar
    // ticking an exercise produces no visible feedback whatsoever.
    await page.getByRole('checkbox').first().check();
    const bar = page.getByRole('status').filter({ hasText: /1 exercice/ });
    await expect(bar).toBeInViewport();
    await expect(bar.getByRole('button', { name: /sur la feuille/i })).toBeVisible();
  });

  test('reordering moves an item and the sheet follows', async ({ page }) => {
    await openDocument(page);
    const boxes = page.getByRole('checkbox');
    await boxes.nth(0).check();
    await boxes.nth(1).check();

    const sheet = page.getByRole('heading', { name: /sur la feuille/i }).locator('..').locator('..');
    const before = await sheet.locator('[data-student-facing]').first().innerText();

    await page.getByRole('button', { name: /^descendre$/i }).first().click();
    const after = await sheet.locator('[data-student-facing]').first().innerText();
    expect(after).not.toBe(before);
  });

  test('an open exercise gets an answer box the teacher sizes', async ({ page }) => {
    await openDocument(page);

    // Only the free-response item offers a box; a bubble item has nothing to
    // write in, so it must not grow the control.
    await page.getByRole('button', { name: /^réponse libre/i }).click();
    await page.getByRole('checkbox').first().check();

    const height = page.getByRole('radiogroup', { name: /hauteur/i });
    await expect(height).toBeVisible();
    await expect(height.getByRole('radio', { name: /5 lignes/ })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    await height.getByRole('radio', { name: /12 lignes/ }).click();
    await expect(height.getByRole('radio', { name: /12 lignes/ })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    await page.getByRole('radiogroup', { name: /fond/i }).getByRole('radio', { name: /quadrillage/i }).click();
    await expect(page.locator('[data-answer-box-control]')).toHaveCount(1);
  });
});
