'use client';

/**
 * The boundary for a component that throws.
 *
 * Every screen in the app handles a *failed request* well — `ErrorState`, a
 * retry, an `apiErrorMessage`. None of them handles a throw during render, and
 * until this file existed there was no boundary at any level of the tree: an
 * exception took the whole app and Next replaced it with its own English
 * "Application error: a client-side exception has occurred", which in
 * production does not even say which component. A teacher reading that
 * concludes Alppy is broken and stops using it.
 *
 * There is a live candidate for it. `toScanMarks` reads `bubble_boxes`
 * defensively, but `PageCard` maps `page.detections` and `DetectionRow` indexes
 * `letters[i]` and `detection.options.map` — a payload from a partially
 * migrated API throws inside the render, on the densest screen in the product.
 *
 * This renders inside the locale layout, so it keeps the app shell and the
 * translations: the teacher stays somewhere that looks like Alppy, with the
 * navigation still under their hand.
 */

import { Button, ErrorState } from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useEffect } from 'react';

export default function LocaleError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations('errors.generic');

  useEffect(() => {
    // The console is where `message` belongs — `api/client.ts` says so, and it
    // is the reason no screen renders it. `digest` is what Next puts in the
    // server log for a production build, and it is the only handle that ties
    // this render to that entry.
    console.error('[alppy] unhandled render error', error.digest ?? '', error);
  }, [error]);

  return (
    <ErrorState
      title={t('title')}
      description={t('body')}
      action={<Button onClick={() => reset()}>{t('action')}</Button>}
    />
  );
}
