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

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? '/api/v1';

/** Fixture mode: the screens render without a backend (tests, design review). */
export function isMockEnabled(): boolean {
  if (process.env.NEXT_PUBLIC_ALPPY_MOCK === '1') return true;
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem('alppy.mock') === '1';
  } catch {
    return false;
  }
}

export interface RequestOptions {
  /** `PUT` is here for the one route that replaces a whole list rather than
   *  patching fields — the class's branch order (D75). */
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  /** Multipart upload; `body` is ignored when this is set. */
  formData?: FormData;
  signal?: AbortSignal;
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
  const { method = 'GET', body, formData, signal, query } = options;
  const url = withQuery(path, query);

  if (isMockEnabled()) {
    const { handleMock } = await import('./mock/handlers');
    return handleMock<T>(method, url, formData ?? body);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${url}`, {
      method,
      // Cookie session: the API sets an HttpOnly cookie, the browser returns it.
      credentials: 'include',
      headers: formData
        ? { Accept: 'application/json' }
        : { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      body: formData ?? (body === undefined ? undefined : JSON.stringify(body)),
      signal: signal ?? null,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
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
  const { method = 'GET', body, signal, query } = options;
  const url = withQuery(path, query);

  if (isMockEnabled()) {
    const { handleMock } = await import('./mock/handlers');
    return handleMock<string>(method, url, body);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${url}`, {
      method,
      credentials: 'include',
      headers: {
        Accept: 'text/html',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal ?? null,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new ApiError(0, 'network_error', 'the API could not be reached');
  }

  if (!response.ok) {
    const error = await parseError(response);
    noteUnauthorized(path, error);
    throw error;
  }
  return response.text();
}
