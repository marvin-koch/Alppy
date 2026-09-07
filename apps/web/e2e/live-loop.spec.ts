import { expect, test } from '@playwright/test';

/**
 * The F1 and F2 loops against the REAL API.
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
  // Serial, and one worker for the whole file: this is the only spec that
  // writes to a shared database, so two browser projects running it at once
  // upload, build and render against each other's rows.
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
    // Scoped to `main`: the shell's class/subject switcher lives in the rail.
    await expect(page.locator('main select')).toHaveCount(1);

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
    // class + subject + source document. The builder is document-first now, so
    // the retrieval path lives behind its own tab.
    await expect(page.locator('main select').first()).toBeVisible();
    await page.getByRole('tab', { name: /proposer pour moi/i }).click();
    await page.getByPlaceholder(/révision fractions/i).fill('fractions');
    await page.getByRole('button', { name: /^proposer des exercices$/i }).click();
    await expect(page.locator('[data-student-facing]').first()).toBeVisible({ timeout: 30_000 });

    await page.getByRole('button', { name: /générer la feuille/i }).click();
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

/**
 * The F2 loop: upload a pile of copies, review them, confirm.
 *
 * The same counterweight, for the same reason. Against the fixture layer the
 * upload client posted `files` where the API declares `file`, and sent no
 * `sheet_id` at all — so every browser upload 422'd, and a scan that reached
 * confirm graded nothing while telling the teacher it had saved. Neither was
 * visible to a mocked spec.
 */
test.describe('@live the F2 scan loop against a real API', () => {
  test.skip(!API || !WEB, 'set ALPPY_LIVE_API and ALPPY_LIVE_WEB to run');
  test.describe.configure({ mode: 'serial' });
  test.setTimeout(180_000);

  test('a teacher can upload copies, review them and confirm', async ({ page }) => {
    await page.goto(`${WEB}/fr/login`);
    await page.getByLabel(/e-?mail/i).fill('demo@alppy.ch');
    await page.locator('input[type="password"]').fill('alppy-demo-2026');
    await page.locator('button[type="submit"]').click();
    await expect(page).not.toHaveURL(/\/login/);

    // --- the upload form asks which sheet, and sends it -------------------
    await page.goto(`${WEB}/fr/scans/new`);
    const sheetPicker = page.locator('main select');
    await expect(sheetPicker).toHaveCount(1);
    await expect(sheetPicker.locator('option')).not.toHaveCount(1); // more than the placeholder
    await sheetPicker.selectOption({ index: 1 });

    const uploaded = page.waitForResponse(
      (r) => r.url().includes('/scans') && r.request().method() === 'POST',
      { timeout: 60_000 },
    );
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'copies.png',
      mimeType: 'image/png',
      buffer: PNG_1PX,
    });

    // 202 is the whole assertion, and it is a strong one: the API declares the
    // file part as `files` and `sheet_id` as a required form field, so a body
    // missing either is a 422. This is exactly what used to happen, invisibly,
    // on every upload from the browser.
    expect((await uploaded).status()).toBe(202);

    // --- and it lands on a review screen that polls itself ---------------
    await expect(page).toHaveURL(/\/scans\/[0-9a-f-]{36}/, { timeout: 30_000 });
    await expect(page.getByRole('button', { name: /valider/i })).toBeVisible();
  });

  test('the review screen shows the page, the questions and the marks', async ({ page }) => {
    await page.goto(`${WEB}/fr/login`);
    await page.getByLabel(/e-?mail/i).fill('demo@alppy.ch');
    await page.locator('input[type="password"]').fill('alppy-demo-2026');
    await page.locator('button[type="submit"]').click();
    await expect(page).not.toHaveURL(/\/login/);

    // Pick, from the API, a scan that actually has readings on it.
    const scans = await page.request.get(`${API}/scans`);
    const list = (await scans.json()) as {
      id: string;
      pages: { detections: unknown[]; image_url: string | null }[];
    }[];
    const reviewable = list.find((s) =>
      s.pages.some((p) => p.detections.length > 0 && p.image_url),
    );
    expect(reviewable, 'seed a scan first: run the F2 upload test').toBeTruthy();

    await page.goto(`${WEB}/fr/scans/${reviewable!.id}`);

    // The scanned page itself, with the detections drawn over it. This is the
    // whole point of the screen, and it used to render neither.
    await expect(page.locator('main img').first()).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('[role="group"]').first()).toBeAttached();
    await expect(page.locator('[data-state]').first()).toBeAttached();

    // A confidence bar per item, and the question it belongs to — not a bare
    // "#7 / low confidence / A B C D", which nobody can adjudicate.
    await expect(page.locator('[role="meter"]').first()).toBeVisible();
    const rowText = await page.locator('main li').first().innerText();
    expect(rowText.length).toBeGreaterThan(20);
  });
});

/** A 1x1 PNG: enough to be accepted, not enough to register as a page. */
const PNG_1PX = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

/**
 * F7 fixes that fixture mode structurally cannot cover.
 *
 * The session guard depends on a real `httpOnly` cookie, and mock mode is
 * exempt from it by design (otherwise the whole screenshot suite would land on
 * the login form). So these live here rather than in `f7-navigation.spec.ts`.
 */
test.describe('@live F7 · the session guard and cross-teacher isolation', () => {
  test.skip(!API || !WEB, 'set ALPPY_LIVE_API and ALPPY_LIVE_WEB to run');
  test.describe.configure({ mode: 'serial' });

  test('a logged-out visitor is sent to login, and comes back where they were', async ({
    page,
  }) => {
    await page.context().clearCookies();
    await page.goto(`${WEB}/fr/classes`);
    // Was: the full authenticated shell wrapped around a generic
    // "something went wrong", indistinguishable from a real outage.
    await expect(page).toHaveURL(/\/fr\/login\?from=%2Ffr%2Fclasses/);

    await page.getByLabel(/e-?mail/i).fill('demo@alppy.ch');
    await page.locator('input[type="password"]').fill('alppy-demo-2026');
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/\/fr\/classes$/);
  });

  test('a colleague cannot read another teacher\'s roster', async ({ request }) => {
    // The demo seed ships two teachers in one school precisely so this is
    // checkable. See decisions-log D23.
    const mine = await request.post(`${API}/auth/login`, {
      data: { email: 'demo@alppy.ch', password: 'alppy-demo-2026' },
    });
    expect(mine.ok()).toBeTruthy();
    const classes = await (await request.get(`${API}/classes`)).json();
    const sevenB = classes.find((c: { code: string }) => c.code === '7B');
    expect(sevenB, 'the demo class is seeded').toBeTruthy();

    await request.post(`${API}/auth/logout`);
    const theirs = await request.post(`${API}/auth/login`, {
      data: { email: 'colleague@alppy.ch', password: 'alppy-demo-2026' },
    });
    expect(theirs.ok()).toBeTruthy();

    for (const path of ['', '/students', '/mastery']) {
      const response = await request.get(`${API}/classes/${sevenB.id}${path}`);
      // 404, never 403: the response must not confirm the id exists.
      expect(response.status(), `GET /classes/{7B}${path}`).toBe(404);
    }
    // ...while shared teaching material stays shared.
    const subjects = await (await request.get(`${API}/subjects`)).json();
    expect(subjects.length).toBeGreaterThan(0);
  });

  test('the class-code field accepts exactly what the server accepts', async ({ page }) => {
    await page.goto(`${WEB}/fr/login`);
    await page.getByLabel(/e-?mail/i).fill('demo@alppy.ch');
    await page.locator('input[type="password"]').fill('alppy-demo-2026');
    await page.locator('button[type="submit"]').click();
    await expect(page).not.toHaveURL(/\/login/);

    await page.goto(`${WEB}/fr/classes/new`);
    const code = page.locator('input').first();
    const submit = page.getByRole('button', { name: /Créer la classe/i });

    // `_CLASS_RE` in alppy/core/uid.py is `\d{1,2}[A-Za-z]{1,2}`. The form
    // allowed three letters, so `11ABC` passed here and 422'd at the server.
    await code.fill('11ABC');
    await expect(submit).toBeDisabled();
    await code.fill('11AB');
    await expect(submit).toBeEnabled();
  });
});
