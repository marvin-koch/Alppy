import { expect, test } from '@playwright/test';

import { MATRIX_CLASS_ID, gotoStable, withDisplay } from './helpers';

/**
 * "Qui enseigne quoi" — the screen that writes to `class_teacher_subject` and
 * `class_subject` (D73, D75).
 *
 * Every assertion here exists because the browser was the only place it could
 * be checked. Four of them are regressions the canvas-vs-browser comparison
 * caught while the screen was being built:
 *
 * 1. The reorder arrows were a 22 px stacked pair — half the 44 px floor this
 *    product holds itself to, on a screen used on a phone.
 * 2. A disabled ghost button painted `--c-surface-2`, so an end-of-list arrow
 *    looked like a small grey box that had appeared out of nowhere.
 * 3. At 390 px the panel header did not wrap: "Retirer" was clipped off the
 *    right edge and the branch could only be removed by aiming at a bare icon.
 * 4. The refusal message was rendered ONLY inside `ConfirmDestructive`'s typed
 *    confirmation field, so on a dialog without one — this one — the count the
 *    server had already sent went nowhere at all.
 *
 * `tsc` can see none of those, and neither can a unit test.
 */

const TEACHING = `/fr/classes/${MATRIX_CLASS_ID}/teaching`;

const panelFor = (page: import('@playwright/test').Page, name: string) =>
  page.locator('li.ard-panel').filter({ has: page.locator('h3', { hasText: name }) });

const branchOrder = async (page: import('@playwright/test').Page) =>
  (await page.locator('li.ard-panel h3').allInnerTexts()).map((s) => s.trim());

test.beforeEach(async ({ page }) => {
  await withDisplay(page, {});
});

test('the class studies a branch its teacher does not take', async ({ page }) => {
  await gotoStable(page, TEACHING);

  // `declared_subject_ids`, not `subject_ids`: history is on 7B's programme and
  // Claire does not teach it. This is the only screen that shows the superset,
  // so it is the only place the gap is visible at all.
  await expect(page.locator('li.ard-panel')).toHaveCount(3);
  expect(await branchOrder(page)).toEqual(['Français', 'Mathématiques', 'Histoire']);

  // Never colour alone: the amber chip is NAMED, and the sentence beside it
  // says what the state means.
  const histoire = panelFor(page, 'Histoire');
  await expect(histoire.getByText('Personne', { exact: true })).toBeVisible();
  await expect(histoire.getByText(/aucun enseignant ne la prend/)).toBeVisible();
});

test('a colleague can be given a branch and taken off it again', async ({ page }) => {
  await gotoStable(page, TEACHING);
  const histoire = panelFor(page, 'Histoire');

  await histoire.getByRole('button', { name: 'Ajouter' }).click();
  await expect(histoire.getByText('Sandra Bieri')).toBeVisible();
  await expect(histoire.getByText('Personne', { exact: true })).toHaveCount(0);

  await histoire.locator('button[aria-label^="Retirer Sandra"]').click();
  await expect(histoire.getByText('Personne', { exact: true })).toBeVisible();
});

test('reordering writes the class order, and the ends have nowhere to go', async ({ page }) => {
  await gotoStable(page, TEACHING);

  const francais = panelFor(page, 'Français');
  // First in the list: up is disabled, and a disabled GHOST keeps its own
  // nature — transparent, no drop. Painting a face made it read as broken.
  const up = francais.getByRole('button', { name: 'Monter' });
  await expect(up).toBeDisabled();
  await expect(up).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');

  await francais.getByRole('button', { name: 'Descendre' }).click();
  await expect
    .poll(async () => branchOrder(page))
    .toEqual(['Mathématiques', 'Français', 'Histoire']);
});

test('declaring adds a branch the class did not study', async ({ page }) => {
  await gotoStable(page, TEACHING);
  await page.getByRole('button', { name: 'Déclarer' }).click();
  await expect.poll(async () => branchOrder(page)).toContain('Allemand');
});

test('removing a branch that still holds sheets is refused, with the count', async ({ page }) => {
  await gotoStable(page, TEACHING);

  await panelFor(page, 'Mathématiques').getByRole('button', { name: /^Retirer$/ }).click();
  const confirm = page.getByRole('button', { name: 'Retirer la discipline' });
  await expect(confirm).toBeEnabled();
  await confirm.click();

  // The count is the whole message: "no longer possible in the current state"
  // names nothing the teacher can act on.
  await expect(page.getByRole('alert').filter({ hasText: 'Mathématiques' })).toHaveCount(0);
  await expect(page.getByText(/porte encore 1 fiche dans la 7B/)).toBeVisible();
  // And the confirm goes cold: pressing it again cannot succeed until the
  // sheets move, so a live button would just do nothing.
  await expect(confirm).toBeDisabled();
  // Nothing was removed.
  expect(await branchOrder(page)).toContain('Mathématiques');
});

test('every control clears the 44 px touch target on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await gotoStable(page, TEACHING);

  const francais = panelFor(page, 'Français');
  for (const name of ['Monter', 'Descendre']) {
    const box = await francais.getByRole('button', { name }).boundingBox();
    expect(box?.height ?? 0, `${name} height`).toBeGreaterThanOrEqual(44);
    expect(box?.width ?? 0, `${name} width`).toBeGreaterThanOrEqual(44);
  }

  // The header wraps rather than clipping: the label has to be readable, not
  // just present in the DOM.
  await expect(francais.getByRole('button', { name: /^Retirer$/ })).toBeVisible();

  // Mobile-first means the page never scrolls sideways.
  const width = await page.evaluate(() => ({
    doc: document.documentElement.scrollWidth,
    win: window.innerWidth,
  }));
  expect(width.doc).toBeLessThanOrEqual(width.win);
});
