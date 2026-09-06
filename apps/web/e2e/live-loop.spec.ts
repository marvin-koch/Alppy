import { expect, test } from '@playwright/test';

/**
 * The F1 loop against the REAL API.
 *
 * Every other spec runs with `NEXT_PUBLIC_ALPPY_MOCK=1`, which is what makes
 * them fast and hermetic — and also means they cannot see a contract drift
 * between the client and the API. They did not: the upload client omitted
 * `subject_id` and every upload 422'd, invisibly, because the fixture layer
 * accepted it.
 *
 * This spec is the counterweight. It is skipped unless `ALPPY_LIVE_API` names
 * a running API, so it never makes the default suite depend on a database:
 *
 *   docker compose up -d
 *   ALPPY_LIVE_API=http://localhost:8000/api/v1 \
 *   ALPPY_LIVE_WEB=http://localhost:3000 pnpm test:e2e --grep @live
 */
const API = process.env.ALPPY_LIVE_API;
const WEB = process.env.ALPPY_LIVE_WEB;

test.describe('@live the F1 loop against a real API', () => {
  test.skip(!API || !WEB, 'set ALPPY_LIVE_API and ALPPY_LIVE_WEB to run');
  test.describe.configure({ mode: 'serial' });
  test.setTimeout(180_000);

  test('a teacher can log in, upload, build, and download both PDFs', async ({ page }) => {
    // --- log in --------------------------------------------------------
    await page.goto(`${WEB}/fr/login`);
    await page.getByLabel(/e-?mail/i).fill('demo@alppy.ch');
    await page.locator('input[type="password"]').fill('alppy-demo-2026');
    await page.locator('button[type="submit"]').click();
    await expect(page).not.toHaveURL(/\/login/);

    // --- the upload form carries a subject, and the request is accepted --
    await page.goto(`${WEB}/fr/sources`);
    await expect(page.locator('select')).toHaveCount(1);

    // Wait for the subject list before touching the file input: the drop zone
    // is disabled until a subject exists to file the book under.
    await expect(page.locator('select option').first()).toBeAttached();

    const upload = page.waitForResponse(
      (r) => r.url().includes('/sources') && r.request().method() === 'POST',
      { timeout: 60_000 },
    );
    await page.locator('input[type="file"]').setInputFiles({
      name: 'live-test.pdf',
      mimeType: 'application/pdf',
      // A minimal but real PDF with a text layer.
      buffer: Buffer.from(
        '%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n' +
          '2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n' +
          '3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n' +
          'trailer<</Root 1 0 R>>\n%%EOF\n',
      ),
    });
    expect((await upload).status()).toBe(202);

    // --- build a sheet ---------------------------------------------------
    await page.goto(`${WEB}/fr/sheets/new`);
    await expect(page.locator('select')).toHaveCount(2); // class + subject
    await page.locator('textarea').first().fill('fractions');
    await page.getByRole('button', { name: /proposer/i }).click();
    await expect(page.locator('[data-student-facing]').first()).toBeVisible({ timeout: 30_000 });

    await page.getByRole('button', { name: /aperçu avant impression/i }).click();
    await expect(page).toHaveURL(/\/sheets\/[0-9a-f-]{36}/);

    // --- the preview is the server's own document ------------------------
    const preview = page.frameLocator('iframe');
    await expect(preview.locator('.print-uid-grid').first()).toBeVisible({ timeout: 30_000 });
    await expect(preview.locator('.sheet-grid-row').first()).toBeVisible();

    // --- both PDFs, actually downloadable --------------------------------
    await page.getByRole('button', { name: /générer les pdf/i }).click();
    const blank = page.getByRole('link', { name: /télécharger la fiche/i });
    await expect(blank).toBeVisible({ timeout: 120_000 });
    await expect(page.getByRole('link', { name: /télécharger le corrigé/i })).toBeVisible();

    // The URL has to serve real bytes: the key used to be recorded while the
    // file sat on the worker's local disk, so this 404'd.
    const href = await blank.getAttribute('href');
    const pdf = await page.request.get(href!);
    expect(pdf.status()).toBe(200);
    expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');
  });

  test('a created sheet is reachable again from the sheet list', async ({ page }) => {
    await page.goto(`${WEB}/fr/login`);
    await page.getByLabel(/e-?mail/i).fill('demo@alppy.ch');
    await page.locator('input[type="password"]').fill('alppy-demo-2026');
    await page.locator('button[type="submit"]').click();
    await expect(page).not.toHaveURL(/\/login/);

    await page.goto(`${WEB}/fr/sheets`);
    const links = page.locator('a[href*="/sheets/"]');
    await expect(links.first()).toBeVisible({ timeout: 30_000 });
  });
});
