import { afterEach, describe, expect, it } from 'vitest';

import { HSTS_HEADER, buildCsp, STATIC_SECURITY_HEADERS, securityHeaders } from './csp';
import { THEME_SCRIPT_CSP_HASH } from './theme-script';

function directive(csp: string, name: string): string | undefined {
  return csp
    .split('; ')
    .find((entry) => entry === name || entry.startsWith(`${name} `));
}

const ORIGINAL = { ...process.env };
afterEach(() => {
  process.env.NEXT_PUBLIC_API_BASE_URL = ORIGINAL.NEXT_PUBLIC_API_BASE_URL;
  process.env.ALPPY_MEDIA_ORIGINS = ORIGINAL.ALPPY_MEDIA_ORIGINS;
});

describe('buildCsp', () => {
  it('carries the nonce and the theme-script hash in script-src', () => {
    const csp = buildCsp({ nonce: 'abc123' });
    expect(directive(csp, 'script-src')).toContain("'nonce-abc123'");
    expect(directive(csp, 'script-src')).toContain(THEME_SCRIPT_CSP_HASH);
  });

  /** The one primitive the policy exists to deny. A `next dev` convenience
   *  that leaked into a build would undo the whole thing silently. */
  it('never allows unsafe-eval outside dev', () => {
    expect(buildCsp({ nonce: 'n' })).not.toContain('unsafe-eval');
    expect(buildCsp({ nonce: 'n', dev: true })).toContain("'unsafe-eval'");
  });

  it('never allows inline script', () => {
    expect(directive(buildCsp({ nonce: 'n' }), 'script-src')).not.toContain("'unsafe-inline'");
  });

  it('refuses framing, plugins and base-tag rewriting', () => {
    const csp = buildCsp({ nonce: 'n' });
    expect(directive(csp, 'frame-ancestors')).toBe("frame-ancestors 'none'");
    expect(directive(csp, 'object-src')).toBe("object-src 'none'");
    expect(directive(csp, 'base-uri')).toBe("base-uri 'none'");
    expect(directive(csp, 'form-action')).toBe("form-action 'self'");
  });

  it('admits the object store in img-src when one is configured', () => {
    process.env.ALPPY_MEDIA_ORIGINS = 'http://localhost:9000, https://cdn.example/bucket';
    const img = directive(buildCsp({ nonce: 'n' }), 'img-src');
    expect(img).toContain('http://localhost:9000');
    expect(img).toContain('https://cdn.example');
  });

  it('keeps img-src same-origin when no object store is configured', () => {
    delete process.env.ALPPY_MEDIA_ORIGINS;
    expect(directive(buildCsp({ nonce: 'n' }), 'img-src')).toBe("img-src 'self' data: blob:");
  });

  /** The preview iframe is a document served BY THE API. `frame-src 'self'`
   *  alone blocked it in every deployment where the API is a second origin —
   *  which is the compose default — and the failure was silent: the preview's
   *  own error check is a `fetch`, and `connect-src` lets that through. */
  it('admits the API origin as a frame source, so the preview can render', () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = 'http://localhost:8000/api/v1';
    expect(directive(buildCsp({ nonce: 'n' }), 'frame-src')).toContain('http://localhost:8000');

    process.env.NEXT_PUBLIC_API_BASE_URL = '/api/v1';
    expect(directive(buildCsp({ nonce: 'n' }), 'frame-src')).toBe("frame-src 'self'");
  });

  /** The compose stack and `pnpm dev` both talk to the API cross-origin; the
   *  production reverse proxy does not, and `/api/v1` must not become a
   *  garbage source expression. */
  it('adds the API origin to connect-src only when it is absolute', () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = 'http://localhost:8000/api/v1';
    expect(directive(buildCsp({ nonce: 'n' }), 'connect-src')).toContain('http://localhost:8000');

    process.env.NEXT_PUBLIC_API_BASE_URL = '/api/v1';
    expect(directive(buildCsp({ nonce: 'n' }), 'connect-src')).toBe("connect-src 'self'");
  });
});

describe('STATIC_SECURITY_HEADERS', () => {
  it('sets nosniff, a referrer policy and a frame refusal', () => {
    const byKey = Object.fromEntries(STATIC_SECURITY_HEADERS.map((h) => [h.key, h.value]));
    expect(byKey['X-Content-Type-Options']).toBe('nosniff');
    expect(byKey['X-Frame-Options']).toBe('DENY');
    // A student uuid lives in the path; `no-referrer-when-downgrade` and the
    // browser default would both send it to the object store.
    expect(byKey['Referrer-Policy']).toBe('strict-origin-when-cross-origin');
  });
});

describe('securityHeaders', () => {
  const base: Parameters<typeof securityHeaders>[0] = {
    env: 'production',
    isDeployment: true,
    dev: false,
    apiBaseUrl: '/api/v1',
    apiOrigin: null,
    mediaOrigins: [],
    s3PublicOrigin: null,
    mockEnabled: false,
    demoMode: false,
  };

  it('adds HSTS on a real deployment', () => {
    const keys = securityHeaders(base).map((h) => h.key);
    expect(keys).toContain('Strict-Transport-Security');
  });

  /** `docker compose up` serves this on http://localhost:3000. Pinning that
   *  host to HTTPS for a year breaks every other local stack on the machine. */
  it('never adds HSTS outside a deployment', () => {
    const keys = securityHeaders({ ...base, env: 'local', isDeployment: false }).map((h) => h.key);
    expect(keys).not.toContain('Strict-Transport-Security');
  });

  /** A year, subdomains included, and no `preload`: the preload list is slow
   *  to leave and the production domain is not settled. */
  it('asks for a year and covers subdomains, without preloading', () => {
    expect(HSTS_HEADER.value).toBe('max-age=31536000; includeSubDomains');
    expect(HSTS_HEADER.value).not.toContain('preload');
  });
});
