import { ApiError } from './client';

/**
 * The teacher-facing sentence for a failed request.
 *
 * `ApiError.message` is the API's own English string — "request body failed
 * validation", "upload exceeds the 50 MB limit" — and `client.ts` says plainly
 * that it is for the console. Rendering it anyway is how a French teacher came
 * to be told `request body failed validation` when the upload form was missing
 * a field. Screens switch on `code`; this is that switch, in one place.
 *
 * `t` is the `errors.code` namespace, passed in so this stays a pure function
 * and the catalogues stay the only place strings live.
 *
 * It never throws. next-intl raises on a missing key rather than echoing it,
 * and both lookups here can miss — an unrecognised `code`, or a caller that
 * handed us the wrong namespace. The second miss used to escape, so a screen
 * that was already showing a handled failure crashed instead of reporting it,
 * which is the worst possible moment to throw.
 */
export function apiErrorMessage(error: unknown, t: (key: string) => string): string {
  const code = error instanceof ApiError ? error.code : null;
  return (code === null ? null : translate(t, code)) ?? translate(t, 'fallback') ?? '';
}

function translate(t: (key: string) => string, key: string): string | null {
  try {
    return t(key);
  } catch {
    return null;
  }
}
