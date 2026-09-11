import { expect, test } from '@playwright/test';

import { gotoStable, withDisplay } from './helpers';

/**
 * The four expensive routes send an `Idempotency-Key`, and a retry sends the
 * SAME one.
 *
 * `RequestOptions` had no `headers` field at all, so the key could not be sent
 * from anywhere — while the API had claimed one on all four routes since the
 * backend pass and two translated refusal sentences sat in the catalogue waiting
 * for a request that never arrived (`idempotency_in_flight`,
 * `idempotency_key_too_long`). That is the "typed on the server, unreachable from
 * the client" shape, from the other side.
 *
 * The failure is injected through the mock's own seam, because in mock mode
 * `apiRequest` never reaches `fetch` — see `MockFailure` in `mock/handlers.ts`.
 * The keys the mock saw are read back from `__alppyMockKeys`.
 */
type KeyLog = { call: string; key: string }[];

async function keysFor(page: import('@playwright/test').Page, fragment: string): Promise<string[]> {
  const seen = await page.evaluate(() => globalThis.__alppyMockKeys ?? []);
  return (seen as KeyLog).filter((e) => e.call.includes(fragment)).map((e) => e.key);
}

test.describe('idempotency keys', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('rendering a sheet sends a key, and the retry after a failure reuses it', async ({
    page,
  }) => {
    // Fail the first render only; the retry meets a working API.
    await page.addInitScript(() => {
      (globalThis as { __alppyMockFail?: unknown[] }).__alppyMockFail = [
        { method: 'POST', pattern: '/render', status: 500, code: 'server_error', times: 1 },
      ];
    });
    await gotoStable(page, '/fr/sheets/00000000-0000-4000-8000-000000000600');

    const render = page.getByRole('button', { name: /générer le pdf|générer|imprimer/i }).first();
    await render.click();
    await expect.poll(() => keysFor(page, '/render')).toHaveLength(1);

    // The same button again: same intention, therefore the same key.
    await render.click();
    await expect.poll(() => keysFor(page, '/render')).toHaveLength(2);

    const keys = await keysFor(page, '/render');
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
  });

  test('a different file selection is a new intent, and gets a new key', async ({ page }) => {
    // The one case a retry must NOT cover. Reusing the key across two different
    // selections would have the server answer the second upload with the pile it
    // built from the first.
    //
    // The upload is made to fail so the screen STAYS PUT: on success it navigates
    // to the pile, and a full page load would reset both the mock's key log and
    // the ref under test — which would make this pass without `restart()` ever
    // being called, and prove nothing.
    await page.addInitScript(() => {
      (globalThis as { __alppyMockFail?: unknown[] }).__alppyMockFail = [
        { method: 'POST', pattern: '/scans', status: 500, code: 'server_error' },
      ];
    });
    await gotoStable(page, '/fr/scans/new');
    await page.getByLabel(/fiche corrigée/i).selectOption({ index: 1 });

    const photo = (name: string) => ({
      name,
      mimeType: 'image/jpeg',
      // A 1×1 JPEG. Nothing in this test decodes it.
      buffer: Buffer.from(
        '/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AJQA/9k=',
        'base64',
      ),
    });

    const input = page.locator('input[type="file"]').first();

    await input.setInputFiles([photo('copie-1.jpg')]);
    await expect.poll(() => keysFor(page, 'POST /scans')).toHaveLength(1);

    // Same screen, no reload: a different pile of photographs.
    await input.setInputFiles([photo('copie-2.jpg')]);
    await expect.poll(() => keysFor(page, 'POST /scans')).toHaveLength(2);

    const keys = await keysFor(page, 'POST /scans');
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).not.toBe(keys[0]);
  });
});
