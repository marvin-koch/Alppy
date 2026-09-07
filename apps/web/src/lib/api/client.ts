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
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
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
    throw new ApiError(0, 'network_error', 'the API could not be reached');
  }

  if (!response.ok) throw await parseError(response);
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

  if (!response.ok) throw await parseError(response);
  return response.text();
}
