import createMiddleware from 'next-intl/middleware';
import { NextResponse, type NextRequest } from 'next/server';
import { buildCsp } from './lib/csp';
import { routing } from './i18n/routing';

const intlMiddleware = createMiddleware(routing);

/** Mirrors `Settings.session_cookie` in `alppy/core/config.py`. */
const SESSION_COOKIE = 'alppy_session';

/** Routes reachable without a session. Everything else needs one. */
const PUBLIC_SEGMENTS = ['/login'];

function isPublic(pathname: string): boolean {
  // The locale prefix is always present at this point (`localePrefix: 'always'`),
  // so strip it before matching: `/fr/login` -> `/login`.
  const withoutLocale = pathname.replace(/^\/[a-z]{2}(?=\/|$)/, '') || '/';
  return PUBLIC_SEGMENTS.some(
    (segment) => withoutLocale === segment || withoutLocale.startsWith(`${segment}/`),
  );
}

/** 128 bits, base64. New for every document: a nonce reused across responses
 *  is a nonce an attacker can read off one page and replay into the next. */
function newNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

/**
 * Locale routing, the session gate, and the security headers.
 *
 * Without the gate a logged-out visitor got the whole authenticated shell —
 * rail, seven destinations, bottom tabs — wrapped around a generic "something
 * went wrong", because every screen simply rendered its query's error state on
 * a 401. That is indistinguishable from a real outage, and it made a brand-new
 * teacher's empty account look like a broken one.
 *
 * The cookie is `httpOnly`, so its mere presence is all the edge can check;
 * the API remains the authority and still answers 401 on a forged or expired
 * one. This is a routing convenience, not the security boundary.
 *
 * The CSP is built here rather than in `next.config.ts` because it carries a
 * per-request nonce, and the nonce reaches Next.js the only way Next.js reads
 * one: through the *request*'s `content-security-policy` header. next-intl
 * copies the incoming headers into its own `NextResponse.next({request})`,
 * so setting them before delegating is what carries them downstream — and
 * Next then stamps the nonce onto every inline script it emits itself.
 * Ours is allowed by hash instead; see `lib/theme-script.ts`.
 */
export default function middleware(request: NextRequest) {
  const nonce = newNonce();
  const csp = buildCsp({ nonce, dev: process.env.NODE_ENV !== 'production' });
  request.headers.set('x-nonce', nonce);
  request.headers.set('content-security-policy', csp);

  const response = withSecurityHeaders(intlMiddleware(request), csp);

  // Fixture mode has no backend and therefore no session cookie. Gating it
  // would redirect the whole screenshot suite to the login screen.
  if (process.env.NEXT_PUBLIC_ALPPY_MOCK === '1') return response;

  // Demo mode: the API answers a cookieless request as the demo teacher
  // (`Settings.demo_mode`), so there is no session to gate on and this would
  // redirect every visitor to a login they do not need. Safe to skip precisely
  // because of what this gate is — a routing convenience, per the note above;
  // the API stays the authority and is where demo mode is really decided.
  //
  // Both halves must be set: the API alone leaves the visitor at /login, the
  // web alone leaves them in an app whose every request 401s.
  if (process.env.NEXT_PUBLIC_ALPPY_DEMO_MODE === '1') return response;

  const { pathname, search } = request.nextUrl;
  if (isPublic(pathname)) return response;
  if (request.cookies.has(SESSION_COOKIE)) return response;

  // Keep where they were headed, so login can return them there.
  const locale = pathname.match(/^\/([a-z]{2})(?=\/|$)/)?.[1] ?? routing.defaultLocale;
  const login = new URL(`/${locale}/login`, request.url);
  const from = `${pathname}${search}`;
  if (from && from !== `/${locale}`) login.searchParams.set('from', from);
  return withSecurityHeaders(NextResponse.redirect(login), csp);
}

/** The rest of the headers are static and live in `next.config.ts`, which also
 *  covers the asset routes this middleware never runs on. */
function withSecurityHeaders(response: NextResponse, csp: string): NextResponse {
  response.headers.set('Content-Security-Policy', csp);
  return response;
}

export const config = {
  // Everything except Next internals, the API proxy and static files.
  matcher: ['/((?!api|_next|_vercel|.*\\..*).*)'],
};
