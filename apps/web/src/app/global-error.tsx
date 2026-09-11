'use client';

/**
 * The boundary of last resort: a throw in the locale layout itself.
 *
 * `[locale]/error.tsx` catches anything thrown below the layout. It cannot
 * catch the layout, because it renders inside it — and the locale layout is
 * where `NextIntlClientProvider`, `Providers` and `AppShell` are mounted, so a
 * failure there is exactly the case where none of them are available.
 *
 * Which is why this file has no translations: it says one fixed sentence in
 * French, the default locale. A localised message would need the provider that
 * has just failed to mount. It also ships its own `<html>` and `<body>` — the
 * root layout deliberately renders neither, the locale layout owns them so it
 * can stamp `lang`.
 *
 * The stylesheet is imported here rather than inherited, for the same reason:
 * `globals.css` is imported by the locale layout, and this renders in a
 * document that never got it. Importing it means this page reads the same
 * tokens as everything else instead of hardcoding two hexes — which the design
 * rule forbids in TypeScript, and rightly (DESIGN.md §10.4).
 */

import './globals.css';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="fr">
      {/* Explicit background: the body never inherits one (DESIGN.md §8). */}
      <body className="flex min-h-screen items-center justify-center bg-canvas p-6 text-ink-900 antialiased">
        <main className="max-w-prose text-center">
          <h1 className="mb-3 font-display text-h2 font-bold">Alppy n’a pas pu démarrer</h1>
          <p className="mb-6 text-body">
            Rechargez la page. Si le problème persiste, signalez-le en indiquant le code
            ci-dessous.
          </p>
          {/* Not the `Button` primitive: that comes from @alppy/ui, and this is
              the boundary for the case where mounting the app failed. A plain
              element with the recipe's classes cannot itself be the problem. */}
          <button
            type="button"
            onClick={() => reset()}
            className="min-h-[44px] rounded-lg bg-primary-600 px-5 py-3 text-body text-white"
          >
            Réessayer
          </button>
          {/* The one handle tying this screen to a line in the server log. */}
          {error.digest ? (
            <p className="mt-6 text-body-s text-ink-500">
              <code className="mono">{error.digest}</code>
            </p>
          ) : null}
        </main>
      </body>
    </html>
  );
}
