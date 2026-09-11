import type { ReactNode } from 'react';

/**
 * The locale layout owns <html> and <body> so it can stamp `lang` correctly.
 * This root exists only because the App Router requires one — and, since F6,
 * because `not-found.tsx` and `global-error.tsx` sit beside it: the two
 * boundaries that render when the locale layout is not there to render them.
 */

/**
 * Per-request for the same reason the locale layout is (D86): Next stamps the
 * CSP nonce onto its own inline scripts only while rendering, so a prerendered
 * page serves un-nonced `__next_f.push` blocks, `script-src` refuses all of
 * them, and hydration never happens. On a normal screen that means a dead page;
 * on the root 404 it was worse and stranger — the document arrived complete,
 * React failed to hydrate the mismatched tree, and the browser was left showing
 * an EMPTY body where the server had sent "Page introuvable". Measured, exactly
 * as the locale layout's note says: `curl` returned the heading and the browser
 * showed nothing.
 *
 * The locale layout below already forces this for every real screen, so this
 * changes nothing about them; it extends the same rule to the two files that
 * render outside it.
 */
export const dynamic = 'force-dynamic';
export default function RootLayout({ children }: { children: ReactNode }) {
  return children;
}
