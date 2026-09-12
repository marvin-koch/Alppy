/**
 * Handing a teacher a file the browser has already got.
 *
 * The exports (`GET /classes/{id}/export`, `GET /students/{id}/export`) return
 * JSON through the normal authenticated client, so there is no URL a teacher
 * can be sent to: the session cookie makes a plain link work, but a plain link
 * would also open a megabyte of JSON in a tab rather than saving it. So the
 * document is fetched, serialised, and handed over as a file.
 *
 * Pretty-printed, and that is not decoration. The reader of this file is a
 * parent's lawyer, a DPO, or whoever is migrating a school off Alppy — a
 * person, opening it in whatever they have. Two hundred kilobytes of minified
 * JSON answers "what do you hold about my child" in a way that is technically
 * complete and practically useless.
 */

/** `7B-2026-27-2026-09-12.json` — sortable, and says what it is at a glance. */
export function exportFilename(subject: string, extension = 'json'): string {
  const today = new Date().toISOString().slice(0, 10);
  const safe = subject
    .normalize('NFD')
    // Strip accents rather than dropping the characters: `Collège` becomes
    // `College`, not `Coll ge`. A filename a teacher cannot recognise is one
    // they will not find again.
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^A-Za-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase();
  return `alppy-${safe || 'export'}-${today}.${extension}`;
}

/**
 * Save an object as a JSON file.
 *
 * The object URL is revoked on the next tick rather than immediately: Safari
 * has not started reading it when `click()` returns, and revoking synchronously
 * produces a download that silently saves nothing.
 */
export function downloadJson(data: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: 'application/json',
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  // Appended before clicking: Firefox ignores a click on a detached anchor.
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
