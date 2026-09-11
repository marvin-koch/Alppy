import { readWebConfig, type WebConfig } from './config';
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

export interface CspOptions {
  /** Per-request, base64. Next.js stamps it onto its own inline bootstrap
   *  scripts when it finds it in the request's CSP header. */
  nonce: string;
  /** `next dev` compiles with `eval`. Allowing it in a real deployment would
   *  hand an injected string the one primitive this policy exists to deny. */
  dev?: boolean;
  /** Read fresh from the environment by default: the middleware runs per
   *  request and the compose stack sets `ALPPY_MEDIA_ORIGINS` at runtime. */
  config?: WebConfig;
}

export function buildCsp({ nonce, dev = false, config = readWebConfig() }: CspOptions): string {
  const { apiOrigin, mediaOrigins } = config;

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
    // Both sheet previews: `src` from the API and `srcDoc`, which the browser
    // resolves against the parent document. The API origin is named here for
    // the same reason it is named in `connect-src` — in the compose stack and
    // in `pnpm dev` it is a second origin, and behind the production reverse
    // proxy it is `/api/v1` and `'self'` already covers it.
    //
    // Leaving it out was worse than it looked: the preview's error path checks
    // a `fetch`, which `connect-src` permits and which therefore SUCCEEDS, so a
    // blocked frame produced a blank A4 with no error at all — and the print
    // button of the day fell through to `window.open`, which worked. The one
    // pre-print check a teacher had was invisible in the shipped default
    // configuration.
    ['frame-src', ["'self'", ...(apiOrigin ? [apiOrigin] : [])]],
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

/**
 * HSTS (D23). One year, subdomains included, and deliberately **no `preload`**:
 * preload is a submission to a browser-vendor list that is slow to leave, and
 * the production domain is not settled yet. Adding it later is a one-word
 * change; getting off the list is not.
 *
 * `includeSubDomains` is what makes it worth having here. The session cookie is
 * host-only, but the object store and any future subdomain are not covered by
 * the apex's own TLS habits — and a teacher on a school wifi typing `alppy.ch`
 * makes exactly one plaintext request, which is the one this removes.
 */
export const HSTS_HEADER = {
  key: 'Strict-Transport-Security',
  value: 'max-age=31536000; includeSubDomains',
} as const;

/**
 * The static headers for a given deployment.
 *
 * Split from the constant because HSTS must not be emitted over plain HTTP:
 * `docker compose up` serves this app on `http://localhost:3000`, and a browser
 * that pins `localhost` to HTTPS for a year has broken every other developer's
 * local stack too. The gate is `ALPPY_ENV`, the same test the API uses for the
 * session cookie's `Secure` flag — "this is a real deployment", stated once.
 *
 * Called from the MIDDLEWARE, not from `next.config.ts`: Next resolves
 * `headers()` at build time into `routes-manifest.json`, so a header gated on a
 * runtime variable would be frozen at whatever the build machine had. A browser
 * applies HSTS to the whole host from any one response, so the document
 * responses the middleware handles are enough — the asset routes it skips do
 * not need their own copy.
 */
export function securityHeaders(
  config: WebConfig = readWebConfig(),
): ReadonlyArray<{ key: string; value: string }> {
  return config.isDeployment
    ? [...STATIC_SECURITY_HEADERS, HSTS_HEADER]
    : STATIC_SECURITY_HEADERS;
}
