/**
 * Every environment variable this app reads, in one place, validated once.
 *
 * This is the web half of `alppy/core/config.py`, and it exists for the same
 * reason (D27). The reads used to be scattered — `middleware.ts` for the two
 * mode flags, `lib/csp.ts` for the API base and the media origins,
 * `lib/api/client.ts` for the API base again — each with its own silent
 * fallback and nothing checking that the values agreed with each other. The
 * API refuses to boot on a combination that cannot work; the web app happily
 * served one. `ALPPY_MEDIA_ORIGINS` out of step with `ALPPY_S3_PUBLIC_ENDPOINT_URL`
 * is the case that costs the most: the scan review screen renders its rows,
 * its verdict buttons and empty frames where the crops should be, and the only
 * explanation is a CSP violation in the browser console.
 *
 * Two shapes on purpose:
 *
 *   · `readWebConfig()` reads `process.env` on every call. The middleware runs
 *     per request and the compose stack sets `ALPPY_MEDIA_ORIGINS` at runtime,
 *     so a value frozen at module load would be the wrong one.
 *   · `assertWebConfig()` runs once, at the bottom of this module, and throws.
 *     A deployment that cannot work should fail at boot, not on the first
 *     teacher's first scan.
 *
 * Every `process.env.NEXT_PUBLIC_*` below is written as a literal member
 * access. Next inlines those into the client bundle by *textual* substitution,
 * so `process.env[name]` with a computed name reads `undefined` in the browser
 * and nowhere else — which is the kind of bug this file is supposed to end.
 */

/** Mirrors `Settings.env`. `local` and `ci` are the development defaults'
 *  home; `staging` and `production` are "this is a real deployment", the same
 *  test the API uses for the session cookie's `Secure` flag and for HSTS. */
export type WebEnv = 'local' | 'ci' | 'staging' | 'production';

const WEB_ENVS: readonly WebEnv[] = ['local', 'ci', 'staging', 'production'];

export interface WebConfig {
  /** `ALPPY_ENV`, defaulting to `local`. Server-side only: it is not a
   *  `NEXT_PUBLIC_` variable, so in the browser this is always `local`. */
  readonly env: WebEnv;
  /** `staging` or `production` — a real deployment. */
  readonly isDeployment: boolean;
  /** `NODE_ENV !== 'production'`: `next dev` compiles with `eval`. */
  readonly dev: boolean;
  /** `NEXT_PUBLIC_API_BASE_URL`, or the same-origin `/api/v1` the reverse
   *  proxy serves. */
  readonly apiBaseUrl: string;
  /** `https://host:port` when `apiBaseUrl` is absolute, else null — a relative
   *  base is already covered by `'self'` in the policy. */
  readonly apiOrigin: string | null;
  /** `ALPPY_MEDIA_ORIGINS`, parsed to origins. What may appear in an `<img>`. */
  readonly mediaOrigins: readonly string[];
  /** `ALPPY_S3_PUBLIC_ENDPOINT_URL` — the API's, repeated here so the two can
   *  be checked against each other. Null when the web container was not told. */
  readonly s3PublicOrigin: string | null;
  /** `NEXT_PUBLIC_ALPPY_MOCK` — fixture mode, no backend. */
  readonly mockEnabled: boolean;
  /** `NEXT_PUBLIC_ALPPY_DEMO_MODE` — the web half of `ALPPY_DEMO_MODE`. */
  readonly demoMode: boolean;
}

/** `https://host:port` for an absolute URL, else null. */
export function originOf(value: string | undefined | null): string | null {
  if (!value) return null;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

/** Space- or comma-separated, so one variable can name a bucket and a CDN. */
function originList(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(/[\s,]+/)
    .map((entry) => originOf(entry) ?? '')
    .filter((entry) => entry !== '');
}

function asEnv(value: string | undefined): WebEnv {
  if (!value) return 'local';
  const lowered = value.toLowerCase();
  if ((WEB_ENVS as readonly string[]).includes(lowered)) return lowered as WebEnv;
  throw new Error(
    `ALPPY_ENV is ${JSON.stringify(value)} — expected one of ${WEB_ENVS.join(', ')}`,
  );
}

export function readWebConfig(): WebConfig {
  const env = asEnv(process.env.ALPPY_ENV);
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? '/api/v1';
  return {
    env,
    isDeployment: env === 'staging' || env === 'production',
    dev: process.env.NODE_ENV !== 'production',
    apiBaseUrl,
    apiOrigin: originOf(apiBaseUrl),
    mediaOrigins: originList(process.env.ALPPY_MEDIA_ORIGINS),
    s3PublicOrigin: originOf(process.env.ALPPY_S3_PUBLIC_ENDPOINT_URL),
    mockEnabled: process.env.NEXT_PUBLIC_ALPPY_MOCK === '1',
    demoMode: process.env.NEXT_PUBLIC_ALPPY_DEMO_MODE === '1',
  };
}

/**
 * Every problem, collected — not the first one.
 *
 * Same reasoning as `_refuse_unsafe_deployment`: a fresh deployment usually has
 * more than one, and finding them one restart at a time is how a checklist gets
 * abandoned half-done.
 */
export function validateWebConfig(config: WebConfig): string[] {
  const problems: string[] = [];

  // Not deployment-gated: a base URL that parses as neither an absolute URL nor
  // a same-origin path is broken everywhere, and the symptom is every request
  // 404ing against the web server itself.
  if (!config.apiOrigin && !config.apiBaseUrl.startsWith('/')) {
    problems.push(
      `NEXT_PUBLIC_API_BASE_URL is ${JSON.stringify(config.apiBaseUrl)}: it must be an ` +
        `absolute URL, or a path beginning with "/" for the same-origin reverse proxy`,
    );
  }

  // The pair that fails silently, and the reason this file exists. The crops
  // and the exercise figures are presigned URLs from the object store, so an
  // origin the policy does not name is an image the browser refuses to load —
  // with no error anywhere a teacher can see.
  if (config.s3PublicOrigin && !config.mediaOrigins.includes(config.s3PublicOrigin)) {
    problems.push(
      `ALPPY_MEDIA_ORIGINS does not contain ${config.s3PublicOrigin}, which is the origin of ` +
        `ALPPY_S3_PUBLIC_ENDPOINT_URL: every scan crop and exercise figure would be blocked ` +
        `by the Content-Security-Policy, leaving empty frames on the review screen`,
    );
  }

  if (!config.isDeployment) return problems;

  if (config.mockEnabled) {
    problems.push(
      'NEXT_PUBLIC_ALPPY_MOCK is 1; the screens render invented fixtures and never talk to ' +
        'the API, which on a real deployment shows a teacher a demo class believing it is theirs',
    );
  }
  if (config.demoMode) {
    problems.push(
      'NEXT_PUBLIC_ALPPY_DEMO_MODE is 1; it stands the session gate aside, and outside a demo ' +
        'there is nothing for it to stand aside for (see ALPPY_DEMO_MODE on the API)',
    );
  }
  if (config.apiOrigin && config.apiOrigin.startsWith('http://')) {
    problems.push(
      `NEXT_PUBLIC_API_BASE_URL is ${config.apiOrigin}: the session cookie is Secure on a real ` +
        'deployment, so it is never sent over plain HTTP and nothing past the login form works',
    );
  }
  for (const origin of config.mediaOrigins) {
    if (origin.startsWith('http://')) {
      problems.push(
        `ALPPY_MEDIA_ORIGINS contains ${origin}; a plain-HTTP image on an HTTPS page is blocked ` +
          'as mixed content, and `upgrade-insecure-requests` rewrites it to a port that is not listening',
      );
    }
  }

  return problems;
}

export function assertWebConfig(config: WebConfig = readWebConfig()): WebConfig {
  const problems = validateWebConfig(config);
  if (problems.length > 0) {
    throw new Error(
      `Refusing to start: the web app's configuration cannot work as given ` +
        `(ALPPY_ENV=${config.env}).\n  - ${problems.join('\n  - ')}`,
    );
  }
  return config;
}

// Checked once, at import. Every module that reads configuration goes through
// this one, so importing any of them is what runs the check — at build time for
// the prerendered shell, at boot for the server, and in the browser for the
// `NEXT_PUBLIC_*` half that was baked into the bundle.
assertWebConfig();
