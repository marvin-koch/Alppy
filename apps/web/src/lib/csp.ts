import { THEME_SCRIPT_CSP_HASH } from './theme-script';

/**
 * The Content-Security-Policy and the fixed security headers.
 *
 * Pure functions on purpose: the policy is the kind of thing that is read
 * once, approved, and then never looked at again, so it is somewhere a test
 * can assert on it rather than a string built inline in the middleware.
 *
 * Two directives are looser than the rest and both are deliberate:
 *
 *   · `style-src` keeps `'unsafe-inline'`. React writes `style={{…}}` as an
 *     inline attribute — the preview scale transform, the progress bars, the
 *     mastery meters — and Next injects a `<style>` block of its own. There is
 *     no nonce path for a style *attribute*, so the alternative is not a
 *     stricter policy, it is a broken layout. Injected CSS cannot execute.
 *
 *   · `img-src` has to admit the object store. Scan crops and exercise figures
 *     are served as presigned URLs from S3/MinIO (`alppy/storage.py`), which is
 *     a different origin from the app in every deployment that is not a single
 *     reverse proxy. `ALPPY_MEDIA_ORIGINS` names it; unset means same-origin
 *     only, which is right for the local-storage backend and wrong the moment
 *     S3 is switched on, so it is set in `docker-compose.yml` beside
 *     `ALPPY_S3_PUBLIC_ENDPOINT_URL`.
 *
 * Everything else is closed: no plugins, no base tag rewriting, no framing,
 * and forms may only post to us.
 */

/** `https://host:port` for an absolute URL, else null. A relative API base
 *  (`/api/v1`, the reverse-proxied default) is already covered by `'self'`. */
function originOf(value: string | undefined): string | null {
  if (!value) return null;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

/** Space- or comma-separated, so one variable can name a bucket and a CDN. */
function origins(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(/[\s,]+/)
    .map((entry) => originOf(entry) ?? '')
    .filter((entry) => entry !== '');
}

export interface CspOptions {
  /** Per-request, base64. Next.js stamps it onto its own inline bootstrap
   *  scripts when it finds it in the request's CSP header. */
  nonce: string;
  /** `next dev` compiles with `eval`. Allowing it in a real deployment would
   *  hand an injected string the one primitive this policy exists to deny. */
  dev?: boolean;
}

export function buildCsp({ nonce, dev = false }: CspOptions): string {
  const apiOrigin = originOf(process.env.NEXT_PUBLIC_API_BASE_URL);
  const mediaOrigins = origins(process.env.ALPPY_MEDIA_ORIGINS);

  const script = [
    "'self'",
    `'nonce-${nonce}'`,
    THEME_SCRIPT_CSP_HASH,
    ...(dev ? ["'unsafe-eval'"] : []),
  ];

  const directives: Array<[string, string[]] | [string]> = [
    ['default-src', ["'self'"]],
    ['script-src', script],
    ['style-src', ["'self'", "'unsafe-inline'"]],
    ['img-src', ["'self'", 'data:', 'blob:', ...mediaOrigins]],
    ['font-src', ["'self'", 'data:']],
    // The API in dev and in the compose stack is a second origin; behind the
    // production reverse proxy it is `/api/v1` and `'self'` already covers it.
    ['connect-src', ["'self'", ...(apiOrigin ? [apiOrigin] : []), ...(dev ? ['ws:'] : [])]],
    // Both sheet previews: `src` from the API (same origin through the proxy)
    // and `srcDoc`, which the browser resolves against the parent document.
    ['frame-src', ["'self'"]],
    ['object-src', ["'none'"]],
    ['base-uri', ["'none'"]],
    ['form-action', ["'self'"]],
    ['frame-ancestors', ["'none'"]],
    ...(dev ? [] : [['upgrade-insecure-requests'] as [string]]),
  ];

  // Flattened explicitly: `[name, sources].join(' ')` stringifies the nested
  // array with commas, and a comma-separated source list is not a source list
  // — the browser drops the whole directive and says nothing.
  return directives
    .map(([name, sources]) => (sources ? [name, ...sources].join(' ') : name))
    .join('; ');
}

/**
 * The headers that never vary, so they can be served by `next.config.ts` for
 * every route including the static assets the middleware never sees.
 *
 * `X-Frame-Options` duplicates `frame-ancestors 'none'` on purpose: the CSP
 * only reaches documents the middleware handles, and the older header is the
 * one that still covers everything else.
 */
export const STATIC_SECURITY_HEADERS: ReadonlyArray<{ key: string; value: string }> = [
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' },
  // A student's id lives in the path (`/classes/…/students/<uuid>/…`), and the
  // scan crops are `<img>` tags pointing at another origin. Without this, that
  // path travels to the object store in `Referer` on every one of them.
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  // `capture="environment"` on the scan upload is a file picker, not a media
  // stream: it needs no camera permission, so nothing here needs one.
  {
    key: 'Permissions-Policy',
    value: 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  },
];
