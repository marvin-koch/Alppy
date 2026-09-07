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
 */
export function apiErrorMessage(
  error: unknown,
  t: (key: string) => string,
): string {
  if (error instanceof ApiError) {
    // next-intl throws on a missing key rather than echoing it, and an
    // unrecognised code must not turn a handled failure into a crash.
    try {
      return t(error.code);
    } catch {
      return t('fallback');
    }
  }
  return t('fallback');
}
