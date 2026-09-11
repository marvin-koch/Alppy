import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * F7 — navigation and overview.
 *
 * Every assertion here corresponds to a defect the F7 review found, and each
 * one failed before the fix. The review's own conclusion was that the suite
 * could not have caught any of them, so these are deliberately about
 * *behaviour a teacher sees*, not about the presence of a component.
 */

test.describe('the class and subject switcher', () => {
  test('is in the shell, and names both dimensions', async ({ page }, testInfo) => {
    await withDisplay(page, {});
    await gotoStable(page, '/fr');

    // On a phone it lives in the drawer; on the desktop, in the rail.
    const root =
      testInfo.project.name === 'phone'
        ? (await page.getByRole('button', { name: 'Ouvrir le menu' }).click(),
          page.locator('[role=dialog]'))
        : page.locator('aside');
    const scope = root.locator('[data-scope-switcher]');
    await expect(scope).toBeVisible();

    // Four dimensions since the school year was wired up (G3): school, then
    // year, then class, then discipline. Each row appears only when it is a real
    // choice, and the fixture teacher has two of each — so all four render.
    //
    // The year sits ABOVE the class deliberately. School and year decide which
    // world you are in; class and discipline narrow it. This assertion is also
    // the reachability guarantee on a phone, where the whole switcher is behind
    // the drawer — which is why `school-year.spec.ts` can stay desktop-only.
    const selects = scope.locator('select');
    await expect(selects).toHaveCount(4);
    await expect(scope.getByLabel(/établissement/i)).toHaveValue(/.+/);
    await expect(scope.getByLabel(/année scolaire/i)).toHaveValue(/.+/);
    await expect(scope.getByLabel(/classe/i)).toHaveValue(/.+/);
    await expect(scope.getByLabel(/discipline/i)).toHaveValue(/.+/);
  });

  test('switching class puts it in the URL and survives a reload', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === 'phone', 'driven through the rail on the desktop');
    await withDisplay(page, {});
    await gotoStable(page, '/fr');

    // By LABEL, never by position: the rail grew a row above this one, and an
    // index-based selector silently retargeted to the school.
    const classSelect = page.locator('aside [data-scope-switcher]').getByLabel(/classe/i);
    const before = await classSelect.inputValue();
    await classSelect.selectOption({ index: 1 });

    // Deep-linkable: the choice has to be in the URL, or sending a colleague a
    // link to a matrix opens whichever class sorts first for them.
    await expect(page).toHaveURL(/[?&]class=/);
    const after = await classSelect.inputValue();
    expect(after).not.toBe(before);

    await page.reload();
    const reloaded = page.locator('aside [data-scope-switcher]').getByLabel(/classe/i);
    await reloaded.waitFor();
    await expect(reloaded).toHaveValue(after);
  });

  test('a bare route reopens the class you were last in', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === 'phone', 'driven through the rail on the desktop');
    await withDisplay(page, {});
    await gotoStable(page, '/fr');

    const rail = () => page.locator('aside [data-scope-switcher]').getByLabel(/classe/i);
    const before = await rail().inputValue();
    await rail().selectOption({ index: 1 });
    // Read the id only once the control has re-rendered, or we capture the old
    // one and assert that nothing changed.
    await expect(rail()).not.toHaveValue(before);
    const chosen = await rail().inputValue();

    // No query string this time. The scope has to come back from storage —
    // and it must not be clobbered by whichever of classes/subjects resolves
    // first, which is exactly how it used to revert to the first class.
    await gotoStable(page, '/fr/adaptive');
    await rail().waitFor();
    await expect(rail()).toHaveValue(chosen);
  });
});

test('the home screen shows subjects, not just classes', async ({ page }) => {
  await withDisplay(page, {});
  await gotoStable(page, '/fr');
  // `GET /home` always returned `subjects`; the screen dropped them.
  const header = page.locator('main header');
  await expect(header.getByText('Disciplines')).toBeVisible();
  await expect(header.getByText('Mathématiques')).toBeVisible();
});

test('a stat label never restates its own value', async ({ page }) => {
  await withDisplay(page, {});
  await gotoStable(page, '/fr');

  // The definition list became a row of action pills when the card gained its
  // band histogram; the rule did not move, only the markup. A pill still has
  // to name the stat and show the value as two different strings.
  const pill = page.locator('a[href*="/scans?class="]').first();
  await expect(pill).toBeVisible();
  const text = (await pill.innerText()).trim();
  const [term, ...rest] = text.split(/\s+/);
  // The label used to render the *value* string with a hard-coded count of 0,
  // so a class with two pending scans read
  // "No corrections pending / 2 corrections pending".
  expect(rest.join(' ')).not.toBe(term);
  expect(term).not.toMatch(/\d/);
});

test('the band caption counts competencies, not answers', async ({ page }) => {
  await withDisplay(page, {});
  await gotoStable(page, '/fr');
  // `band_counts` counts (student x competency) CELLS. Captioning it
  // "18 réponses" named the wrong quantity entirely.
  //
  // The five legend numbers no longer each carry a unit — repeating it per
  // band, per class, would be five noisy captions saying one thing. The bar
  // names its quantity ONCE instead, and that sentence is what has to be
  // there: a bar of five numbers that never says what it counts is the same
  // failure in a quieter voice.
  await expect(page.getByText(/élève × compétence/)).toBeVisible();
  await expect(page.getByText(/\d+ réponses/)).toHaveCount(0);
});

test('the pending-corrections count leads somewhere', async ({ page }) => {
  await withDisplay(page, {});
  await gotoStable(page, '/fr');
  // The overview counted work it offered no way to reach: there was no
  // `/scans` index at all, and the count was plain text.
  const link = page.locator('a[href*="/scans?class="]').first();
  await expect(link).toBeVisible();
  await link.click();
  await expect(page.locator('h1')).toContainText('corrections');
});

test('a teacher with no classes can actually create one', async ({ page }) => {
  await withDisplay(page, {});
  await page.route('**/api/v1/classes', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 200, body: '[]', contentType: 'application/json' });
      return;
    }
    await route.continue();
  });
  await gotoStable(page, '/fr/classes');

  // The empty state used to have no action at all — and it is where the home
  // screen's "create a class" sends a brand-new teacher.
  const action = page.getByRole('link', { name: /Créer la classe/i }).first();
  await expect(action).toBeVisible();
  await action.click();
  await expect(page).toHaveURL(/\/classes\/new$/);
  await expect(page.locator('h1')).toContainText('Nouvelle classe');
});

test('every route has its own title', async ({ page }) => {
  await withDisplay(page, {});
  const seen = new Set<string>();
  for (const route of ['/fr/classes', '/fr/sheets', '/fr/scans', '/fr/settings']) {
    await gotoStable(page, route);
    const title = await page.title();
    expect(title, `${route} still has the generic title`).not.toBe('Alppy');
    seen.add(title);
  }
  expect(seen.size, 'each route names itself').toBe(4);
});

test('the two navigation landmarks are told apart', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'phone', 'both landmarks exist on the phone');
  await withDisplay(page, {});
  await gotoStable(page, '/fr');
  // Both were labelled "Accueil" — the name of a destination, not of a region.
  const names = await page
    .locator('nav[aria-label]')
    .evaluateAll((els) => els.map((el) => el.getAttribute('aria-label')));
  expect(new Set(names).has('Accueil')).toBe(false);
});
