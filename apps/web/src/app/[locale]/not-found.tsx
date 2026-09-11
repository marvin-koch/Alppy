'use client';

/**
 * A URL that does not resolve, inside the app.
 *
 * `errors.notFound.{title,body,action}` has been translated three times since
 * the catalogues were written and referenced by nothing (F30) — because there
 * was no `not-found.tsx` at any level to render it, while `notFound()` is
 * genuinely called (`[locale]/layout.tsx` for an unknown locale, and the
 * detail screens for a missing row). Until this file existed, a typo'd URL or
 * a stale bookmark got Next's default 404: English, unstyled, outside the app
 * shell, on a product that is otherwise carefully trilingual.
 *
 * The dead strings are now the live ones. Nothing new was written for this.
 */

import { Button, EmptyState } from '@alppy/ui';
import { useTranslations } from 'next-intl';

import { Link } from '@/i18n/navigation';

export default function LocaleNotFound() {
  const t = useTranslations('errors.notFound');

  // `EmptyState`, not `ErrorState`: nothing failed. The address is simply not
  // one of ours, and a red warning glyph would tell the teacher that something
  // is broken when the honest message is "there is nothing here".
  return (
    <EmptyState
      title={t('title')}
      description={t('body')}
      action={
        <Link href="/" className="no-underline">
          <Button variant="primary">{t('action')}</Button>
        </Link>
      }
    />
  );
}
