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
/** The `errors.code` namespace, as next-intl hands it over. */
type Translate = (key: string, values?: Record<string, string | number>) => string;

export function apiErrorMessage(error: unknown, t: Translate): string {
  const code = error instanceof ApiError ? error.code : null;
  return (
    (code === null ? null : translate(t, code, valuesFor(error))) ?? translate(t, 'fallback') ?? ''
  );
}

/**
 * What a sentence needs beyond its code.
 *
 * Only one so far, and it is the one that most needed it: "réessayez plus
 * tard" is not an instruction, and the envelope has been carrying the actual
 * number of seconds in `details.retry_after_s` all along (`api/errors.py`,
 * which also puts it in `Retry-After`). Rounded up, because telling someone to
 * wait 0 seconds after refusing them is worse than saying nothing.
 */
function valuesFor(error: unknown): Record<string, string | number> | undefined {
  if (!(error instanceof ApiError) || error.code !== 'rate_limited') return undefined;
  const seconds = error.details?.['retry_after_s'];
  return { seconds: Math.max(1, Math.ceil(Number(seconds) || 60)) };
}

function translate(
  t: Translate,
  key: string,
  values?: Record<string, string | number>,
): string | null {
  try {
    return t(key, values);
  } catch {
    return null;
  }
}

/**
 * The failing request's id, when the failure carries one.
 *
 * Separate from `apiErrorMessage` because it answers a different question and is
 * addressed to a different reader: the sentence is for the teacher, this is for
 * whoever they report the problem to. `api/errors.py` puts it on every envelope
 * and `client.ts` has always parsed it; until now only the `global-error`
 * boundary rendered it, which is the boundary least likely to fire (G18).
 */
export function requestIdOf(error: unknown): string | null {
  return error instanceof ApiError ? error.requestId : null;
}
