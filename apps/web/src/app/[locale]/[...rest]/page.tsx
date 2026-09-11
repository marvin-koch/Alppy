import { notFound } from 'next/navigation';

/**
 * Everything under a valid locale that matches no route.
 *
 * Without this, an unmatched path never enters the `[locale]` segment at all:
 * Next finds no matching page, 404s at the root, and answers with
 * `app/not-found.tsx` — which is outside `NextIntlClientProvider` and therefore
 * says "Page introuvable" to a German teacher who typed `/de/klassn`. This
 * catch-all claims the path so that `notFound()` is raised *inside* the locale
 * layout, where `[locale]/not-found.tsx` renders it with the right catalogue
 * and inside the app shell — the navigation still under the teacher's hand.
 *
 * The root boundary stays, and keeps the case this cannot reach: a locale that
 * is not one of ours (`/it/classes`), where the layout itself calls
 * `notFound()` and there is no provider to be inside of.
 */
export default function CatchAllNotFound(): never {
  notFound();
}
