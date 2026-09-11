import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * The upload screen refuses what it can refuse locally, and says which file.
 *
 * There were no client-side checks at all: a teacher could select a folder of
 * 200 files, or a video by mistake, and find out two minutes later from a 413 —
 * or not find out, on a school connection that simply stalled. A courtesy and
 * never a control, the framing `sources/page.tsx` already uses: the API validates
 * all three again and its answer is the one that decides.
 *
 * This screen had NO fixture coverage before this pass. The only sheet in the
 * fixtures had `rendered_at: null` and the screen offers only rendered sheets, so
 * every visit landed on "Aucune fiche imprimée" — which is why a missing size
 * check went unnoticed. `fixtures.renderedSheet` is what opens the door.
 */
const PHOTO = {
  mimeType: 'image/jpeg',
  buffer: Buffer.from(
    '/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AJQA/9k=',
    'base64',
  ),
};

async function uploadScreen(page: import('@playwright/test').Page) {
  await gotoStable(page, '/fr/scans/new');
  // The screen is reachable at all only because a rendered sheet exists.
  await expect(page.getByText(/aucune fiche imprimée/i)).toHaveCount(0);
  await page.getByLabel(/fiche corrigée/i).selectOption({ index: 1 });
  return page.locator('input[type="file"]').first();
}

test.describe('what the upload screen refuses locally', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('asks for the sheet before it will take a photograph', async ({ page }) => {
    await gotoStable(page, '/fr/scans/new');
    const input = page.locator('input[type="file"]').first();

    await input.setInputFiles([{ name: 'copie.jpg', ...PHOTO }]);

    await expect(page.getByText(/choisissez d'abord la fiche/i)).toBeVisible();
    // And nothing was sent.
    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls.some((c) => c.startsWith('POST /scans'))).toBe(false);
  });

  test('refuses a pile larger than the API will take, and names the count', async ({ page }) => {
    const input = await uploadScreen(page);

    await input.setInputFiles(
      Array.from({ length: 121 }, (_, i) => ({ name: `copie-${i}.jpg`, ...PHOTO })),
    );

    // The message carries both numbers: "121 chosen, 120 at most".
    await expect(page.getByText(/121/)).toBeVisible();
    await expect(page.getByText(/120/)).toBeVisible();
    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls.some((c) => c.startsWith('POST /scans'))).toBe(false);
  });

  test('refuses a file that is neither an image nor a PDF, by name', async ({ page }) => {
    const input = await uploadScreen(page);

    await input.setInputFiles([
      { name: 'copie.jpg', ...PHOTO },
      { name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('pas une copie') },
    ]);

    // Named, not just counted: in a pile of thirty, "one file is wrong" is not
    // something a teacher can act on.
    await expect(page.getByText(/notes\.txt/)).toBeVisible();
    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls.some((c) => c.startsWith('POST /scans'))).toBe(false);
  });

  test('accepts a normal pile and sends it', async ({ page }) => {
    const input = await uploadScreen(page);

    await input.setInputFiles([
      { name: 'copie-1.jpg', ...PHOTO },
      { name: 'copie-2.jpg', ...PHOTO },
    ]);

    await expect
      .poll(async () => {
        const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
        return calls.some((c) => c.startsWith('POST /scans'));
      })
      .toBe(true);
  });
});
