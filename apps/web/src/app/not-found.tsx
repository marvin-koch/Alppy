'use client';

/**
 * A 404 outside any locale.
 *
 * `[locale]/not-found.tsx` covers a bad URL *inside* the app, but it renders
 * inside the locale layout — and the most likely 404 of all is thrown BY that
 * layout: `if (!isAppLocale(locale)) notFound()`. A stale bookmark carrying an
 * old locale, or `/it/classes`, lands here, where there is no
 * `NextIntlClientProvider` because the locale it would have been given is not
 * one we have.
 *
 * So, as with `global-error.tsx`: own `<html>`, own stylesheet import, one
 * fixed sentence in the default locale, and a link into the app proper — from
 * where every other 404 is translated.
 */

import './globals.css';

export default function RootNotFound() {
  return (
    <html lang="fr">
      <body className="flex min-h-screen items-center justify-center bg-canvas p-6 text-ink-900 antialiased">
        <main className="max-w-prose text-center">
          <h1 className="mb-3 font-display text-h2 font-bold">Page introuvable</h1>
          <p className="mb-6 text-body">Cette adresse ne correspond à aucune page d’Alppy.</p>
          <a
            href="/fr"
            className="inline-block min-h-[44px] rounded-lg bg-primary-600 px-5 py-3 text-body text-white no-underline"
          >
            Retour à l’accueil
          </a>
        </main>
      </body>
    </html>
  );
}
