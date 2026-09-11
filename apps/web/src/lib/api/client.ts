import { readWebConfig } from '../config';
import type { ApiErrorBody } from './types';

/**
 * One error shape for the whole app, mirroring `alppy/api/errors.py`. Screens
 * switch on `code`; `message` is for the console, never for the teacher — the
 * teacher-facing strings are localised in the catalogues.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    requestId: string | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  /** The API is not running at all — the app degrades, it does not crash. */
  get isOffline(): boolean {
    return this.code === 'network_error';
  }
}

// Read through `lib/config.ts` (D27), which is also where the check lives that
// this base and `ALPPY_MEDIA_ORIGINS` describe the same deployment.
export const API_BASE = readWebConfig().apiBaseUrl;

/**
 * Fixture mode: the screens render without a backend (tests, design review).
 *
 * Two switches, and they are not equals. The build-time flag is the real one and
 * it is what CI and the screenshot suite set. The `localStorage` key is a
 * convenience for driving fixture mode inside an already-running dev or staging
 * build — the e2e suite seeds it, and it is how `/_gallery` is reached by hand.
 *
 * The runtime key is gated on the build NOT being production (G31). Before, anyone
 * could flip a production deployment into fixture mode from devtools and reach
 * `/_gallery`. No real data was ever exposed — the fixtures are invented, and a
 * browser in fixture mode simply stops talking to the API — but a teacher who did
 * it by accident would be looking at a demo class, believing it was theirs, on a
 * screen that shows bands and marks. That is a worse failure than a missing
 * feature, and the gate costs nothing: the dev and staging builds where the key is
 * useful are not production builds.
 */
export function isMockEnabled(): boolean {
  const config = readWebConfig();
  if (config.mockEnabled) return true;
  if (!config.dev) return false;
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem('alppy.mock') === '1';
  } catch {
    return false;
  }
}

/**
 * How long a request is given before the client gives up.
 *
 * Nothing had a deadline. `apiRequest` accepted a `signal` and exactly one caller
 * passed one (a debounce guard), so a request that never answered — a hung
 * connection, a proxy holding the socket open, a school firewall swallowing the
 * response — left its screen on the skeleton forever. There is no browser default
 * worth relying on here: Chrome's own network timeout is minutes long.
 *
 * Two budgets, because the work is not comparable. A JSON read or write is a
 * round trip and 20s is already generous. A multipart scan upload is up to 120
 * photographs over a school's uplink, and cutting that off at 20s would abort
 * work that was progressing perfectly well — which is why `uploadScan` and
 * `addScanPages` get their own, much longer, budget.
 */
export const REQUEST_TIMEOUT_MS = 20_000;
export const UPLOAD_TIMEOUT_MS = 10 * 60_000;

/**
 * The caller's signal and the deadline, as one signal.
 *
 * `AbortSignal.any` so a caller's own abort (a debounce, an unmounting screen)
 * still works and is not replaced by the timeout. Guarded because both statics are
 * recent: where either is missing the caller's signal is used alone and the
 * request behaves exactly as it did before, which is the honest degradation — a
 * missing deadline is what this fixes, not a reason to fail the request.
 */
function withDeadline(signal: AbortSignal | undefined, ms: number): AbortSignal | undefined {
  if (typeof AbortSignal === 'undefined' || typeof AbortSignal.timeout !== 'function') {
    return signal;
  }
  const deadline = AbortSignal.timeout(ms);
  if (!signal) return deadline;
  if (typeof AbortSignal.any !== 'function') return signal;
  return AbortSignal.any([signal, deadline]);
}

/**
 * Told apart from the caller's own abort, and from being offline.
 *
 * A timeout is not `network_error`: "L'application n'a pas pu joindre le serveur"
 * is wrong and misleading when the server was reached and simply never finished.
 * It is also not the caller's abort, which must stay an `AbortError` so
 * react-query keeps treating it as a cancellation rather than a failure.
 */
function abortToError(cause: DOMException, signal: AbortSignal | undefined): unknown {
  // `TimeoutError` is what `AbortSignal.timeout` reports through `signal.reason`.
  const reason = (signal as { reason?: unknown } | undefined)?.reason;
  const timedOut = reason instanceof DOMException && reason.name === 'TimeoutError';
  if (!timedOut) return cause;
  return new ApiError(0, 'timeout', 'the API did not answer in time');
}

export interface RequestOptions {
  /** `PUT` is here for the one route that replaces a whole list rather than
   *  patching fields — the class's branch order (D75). */
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  /** Multipart upload; `body` is ignored when this is set. */
  formData?: FormData;
  signal?: AbortSignal;
  /**
   * Extra request headers, merged over the defaults.
   *
   * This exists for `Idempotency-Key` (D98, `api/deps.py:idempotency_key`). Four
   * routes are expensive to repeat — uploading a pile, rendering a sheet, a
   * differentiation batch and its render — and the API has claimed a key on all
   * four since the backend pass, with two translated refusal sentences waiting in
   * the catalogue (`idempotency_in_flight`, `idempotency_key_too_long`). The
   * client had no way to send one, so neither sentence could ever fire.
   *
   * Merged LAST on purpose, so a caller can override `Accept`; it cannot remove
   * `credentials: 'include'`, which is not a header.
   */
  headers?: Record<string, string>;
  /** Overrides `REQUEST_TIMEOUT_MS`. The scan uploads pass `UPLOAD_TIMEOUT_MS`. */
  timeoutMs?: number;
  /** An array value is appended once per element, which is what FastAPI reads
   *  as a repeated query parameter (`?kind=a&kind=b`). Joining it into one
   *  comma-separated value would arrive as a single unparseable string. */
  query?: Record<string, string | number | boolean | undefined | null | readonly string[]>;
}

function withQuery(path: string, query: RequestOptions['query']): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      for (const entry of value) if (entry !== '') params.append(key, String(entry));
      continue;
    }
    params.append(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function parseError(response: Response): Promise<ApiError> {
  let code = 'http_error';
  let message = response.statusText || 'request failed';
  let details: Record<string, unknown> = {};
  let requestId: string | null = null;
  try {
    const body = (await response.json()) as Partial<ApiErrorBody>;
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details ?? {};
      requestId = body.error.request_id ?? null;
    }
  } catch {
    /* A proxy or a crash can answer with HTML; the status still tells us enough. */
  }
  return new ApiError(response.status, code, message, details, requestId);
}

/* ------------------------------------------------------------------------
 * The session expiring under a teacher's hands
 *
 * The cookie is a stateless signed token with a 12-hour life and no refresh
 * (`core/config.py`). The middleware gate checks that it is *present*, and only
 * on a navigation — so a teacher who signs in at 07:50 on Monday and comes back
 * to the same tab on Tuesday sees a screen that looks like it is working: the
 * query cache serves the pile she was reviewing, and every verdict she presses
 * goes out without a cookie and comes back 401. Nothing navigates, so nothing
 * redirects; `apiErrorMessage` has no `unauthorized` entry and falls through to
 * "L'envoi a échoué. Réessayez." She retries. It fails the same way.
 *
 * `docs/reviews/F7-review.md:178-196` found this on 2026-09-06 and offered two
 * directions — a middleware guard on the cookie, OR a client boundary that
 * redirects on `isUnauthorized`. Only the first shipped (`F7-fixes.md` F-3),
 * and it covers a visitor who is not signed in, which is the other case. This
 * is the second direction, which is why `ApiError.isUnauthorized` existed with
 * zero callers for five days.
 *
 * A settable handler rather than a redirect written here: this module knows
 * about HTTP and nothing about routing or about the query cache, and the two
 * things that have to happen — clear the cache, then leave — both belong to the
 * app shell. `Providers` registers it.
 * --------------------------------------------------------------------- */

type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

/** Registered by `Providers`; null outside a mounted app (tests, SSR). */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

/**
 * `/auth/me` is the app ASKING whether there is a session. A 401 is that
 * question's answer, not a session that has just died, and treating it as one
 * would redirect the login screen to itself.
 */
function isSessionProbe(path: string): boolean {
  return path.startsWith('/auth/me') || path.startsWith('/auth/login');
}

function noteUnauthorized(path: string, error: ApiError): void {
  if (!error.isUnauthorized || isSessionProbe(path)) return;
  unauthorizedHandler?.();
}

/* ------------------------------------------------------------------------
 * Whether the API is answering at all
 *
 * `navigator.onLine` answers a different and weaker question — whether the
 * machine believes it has a network — and a school wifi that associates but
 * routes nowhere reports `true` throughout. What a teacher needs to know is
 * whether Alppy is reachable, and the only thing that knows that is the last
 * request that tried.
 *
 * So every request reports its outcome here, and `lib/connection.ts` turns
 * that into the one bar in the shell. This is the second caller of the two
 * predicates that were written and never used: `isUnauthorized` above,
 * `isOffline` here.
 * --------------------------------------------------------------------- */

type ReachabilityListener = (reachable: boolean) => void;

const reachabilityListeners = new Set<ReachabilityListener>();

/** Subscribe to "did the last request reach the API". Returns an unsubscribe. */
export function onApiReachability(listener: ReachabilityListener): () => void {
  reachabilityListeners.add(listener);
  return () => reachabilityListeners.delete(listener);
}

function noteReachability(reachable: boolean): void {
  for (const listener of reachabilityListeners) listener(reachable);
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, formData, signal, query, headers, timeoutMs } = options;
  const deadline = withDeadline(signal, timeoutMs ?? REQUEST_TIMEOUT_MS);
  const url = withQuery(path, query);

  if (isMockEnabled()) {
    const { handleMock } = await import('./mock/handlers');
    // Through the SAME 401 path a real response takes (T11).
    //
    // This used to `return handleMock(...)` directly, which put the mock's
    // `ApiError(401)` on a route that never reaches `noteUnauthorized` below —
    // so the redirect-and-clear-cache behaviour was not merely untested, it was
    // unreachable from any E2E test, because the fixture layer IS the transport
    // in those runs. The bug was in the test seam, not in the product, which is
    // the kind that survives longest.
    try {
      return await handleMock<T>(method, url, formData ?? body, headers);
    } catch (error) {
      if (error instanceof ApiError) noteUnauthorized(path, error);
      throw error;
    }
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${url}`, {
      method,
      // Cookie session: the API sets an HttpOnly cookie, the browser returns it.
      credentials: 'include',
      headers: formData
        ? { Accept: 'application/json', ...headers }
        : {
            Accept: 'application/json',
            ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
            ...headers,
          },
      body: formData ?? (body === undefined ? undefined : JSON.stringify(body)),
      signal: deadline ?? null,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') {
      // A deadline that expired is a failure with its own sentence; a caller's own
      // abort stays an AbortError so react-query keeps reading it as a
      // cancellation rather than reporting it to the teacher.
      const mapped = abortToError(cause, deadline);
      if (mapped instanceof ApiError) throw mapped;
      throw cause;
    }
    const offline = new ApiError(0, 'network_error', 'the API could not be reached');
    noteReachability(false);
    throw offline;
  }

  // A 4xx or a 5xx still proves the API is there and answering — being told
  // "no" is not the same as being unable to ask.
  noteReachability(true);
  if (!response.ok) {
    const error = await parseError(response);
    noteUnauthorized(path, error);
    throw error;
  }
  if (response.status === 204) return undefined as T;

  const text = await response.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

/**
 * Same request, but the body is returned verbatim instead of parsed.
 *
 * `POST /sheets/preview` answers with the print document itself — the same
 * markup the PDF renderer consumes — so there is no JSON to parse. Errors still
 * arrive as the usual envelope and still become an `ApiError`, which is the
 * whole reason this shares a code path with `apiRequest` rather than being a
 * bare `fetch` at the call site: a 422 saying "this statement is taller than a
 * page" has to reach the teacher as a message, not as raw JSON rendered inside
 * the preview frame.
 */
export async function apiRequestText(path: string, options: RequestOptions = {}): Promise<string> {
  const { method = 'GET', body, signal, query, headers, timeoutMs } = options;
  const deadline = withDeadline(signal, timeoutMs ?? REQUEST_TIMEOUT_MS);
  const url = withQuery(path, query);

  if (isMockEnabled()) {
    const { handleMock } = await import('./mock/handlers');
    // Through the SAME 401 path a real response takes (T11).
    //
    // This used to `return handleMock(...)` directly, which put the mock's
    // `ApiError(401)` on a route that never reaches `noteUnauthorized` below —
    // so the redirect-and-clear-cache behaviour was not merely untested, it was
    // unreachable from any E2E test, because the fixture layer IS the transport
    // in those runs. The bug was in the test seam, not in the product, which is
    // the kind that survives longest.
    try {
      return await handleMock<string>(method, url, body, headers);
    } catch (error) {
      if (error instanceof ApiError) noteUnauthorized(path, error);
      throw error;
    }
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${url}`, {
      method,
      credentials: 'include',
      headers: {
        Accept: 'text/html',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: deadline ?? null,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') {
      const mapped = abortToError(cause, deadline);
      if (mapped instanceof ApiError) throw mapped;
      throw cause;
    }
    throw new ApiError(0, 'network_error', 'the API could not be reached');
  }

  if (!response.ok) {
    const error = await parseError(response);
    noteUnauthorized(path, error);
    throw error;
  }
  return response.text();
}
