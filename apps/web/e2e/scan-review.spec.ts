import { expect, test } from '@playwright/test';

import { gotoStable, showEveryItem, withDisplay } from './helpers';

/**
 * The review of a written answer. The mock scan carries one open item on its
 * first page: the box as cut from the paper, the model's transcription and
 * verdict, and a control to overrule it. What matters is that the teacher can
 * disagree in one gesture and that the machine's reading stays on screen.
 */
test.describe('scan review · written answers', () => {
  test.beforeEach(async ({ page }) => {
    await withDisplay(page, {});
  });

  test('a written answer shows its crop, its reading and a verdict to overrule', async ({
    page,
  }) => {
    await gotoStable(page, '/fr/scans/00000000-0000-4000-8000-000000000800');
    // The pile opens filtered to what needs a human (G12); this answer was read
    // confidently, so it is settled and hidden until the filter is cleared.
    await showEveryItem(page);

    const card = page.locator('[data-open-answer]').first();
    await expect(card).toBeVisible();
    await expect(card.getByRole('img', { name: /réponse écrite/i })).toBeVisible();
    await expect(card.getByText('3/4 + 1/8 = 6/8 + 1/8 = 7/8')).toBeVisible();
    await expect(card.getByText(/lu par l'ia/i)).toBeVisible();

    const verdict = card.getByRole('radiogroup', { name: /verdict/i });
    await expect(verdict.getByRole('radio', { name: /^juste$/i })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    await verdict.getByRole('radio', { name: /^faux$/i }).click();

    await expect(card.getByText(/corrigé par vous/i)).toBeVisible();
    // The machine's verdict is kept beside the teacher's, not under it.
    await expect(card.getByText(/verdict de la machine\s*: juste/i)).toBeVisible();

    const calls = await page.evaluate(() => globalThis.__alppyMockCalls ?? []);
    expect(calls.some((c) => c.startsWith('PATCH') && c.includes('/detections/'))).toBe(true);
  });
});
