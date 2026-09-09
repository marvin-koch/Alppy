import createMiddleware from 'next-intl/middleware';
import { NextResponse, type NextRequest } from 'next/server';
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

/**
 * Locale routing, plus the session gate.
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
 */
export default function middleware(request: NextRequest) {
  const response = intlMiddleware(request);

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
  return NextResponse.redirect(login);
}

export const config = {
  // Everything except Next internals, the API proxy and static files.
  matcher: ['/((?!api|_next|_vercel|.*\\..*).*)'],
};
