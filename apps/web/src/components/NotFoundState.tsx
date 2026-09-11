'use client';

import { ErrorState } from '@alppy/ui';
import { useTranslations } from 'next-intl';

import { Link } from '@/i18n/navigation';

/**
 * A thing that is gone, or was never this teacher's.
 *
 * Ownership is resolved from data and a colleague's class reads as **404, never
 * 403**, so a response cannot confirm that an id exists. That makes a 404 the
 * ordinary answer to a stale bookmark, a link from a colleague, a class a teacher
 * stopped teaching in February — and every one of those screens offered
 * "réessayez" and a retry button, which re-asks a question the server has already
 * answered and will answer the same way for ever (G26).
 *
 * One component rather than the same six lines on seven screens, because the two
 * things that make it correct are easy to get wrong separately: it must NOT offer a
 * retry, and it must offer somewhere real to go instead. A dead end with a useless
 * button is what it replaces.
 *
 * No `requestId`: a 404 is an answer, not a malfunction, and sending a teacher to
 * support about a class that is simply no longer theirs wastes everyone's time.
 */
export function NotFoundState({
  backHref,
  backLabel,
}: {
  /** Where the teacher actually wants to be instead. */
  backHref: string;
  backLabel: string;
}) {
  const te = useTranslations('errors.generic');
  const tcode = useTranslations('errors.code');

  return (
    <ErrorState
      title={te('title')}
      description={tcode('not_found')}
      action={
        <Link href={backHref} className="ard-btn" data-variant="primary">
          {backLabel}
        </Link>
      }
    />
  );
}
