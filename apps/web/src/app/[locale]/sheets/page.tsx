'use client';

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  IlloCompass,
  LoadingState,
  Panel,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';

import { Link } from '@/i18n/navigation';
import { useSheets } from '@/lib/api/queries';
import { useFormatters } from '@/lib/format';

/**
 * The list of sheets the teacher has built.
 *
 * This route did not exist: navigation pointed straight at `/sheets/new`, home
 * printed the last sheet's title as plain text, and the only way into
 * `/sheets/[id]` was the redirect immediately after creating it. Close the tab
 * and the sheet was gone.
 */
export default function SheetsIndexPage() {
  const t = useTranslations('sheets');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const fmt = useFormatters();
  const { data, isLoading, isError, refetch } = useSheets();

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1>{t('allSheets')}</h1>
        <Link href="/sheets/new" className="ard-btn" data-variant="primary">
          {t('new')}
        </Link>
      </div>

      {isLoading ? (
        <LoadingState shape="list" label={tc('loading')} rows={4} />
      ) : isError ? (
        <ErrorState
          title={te('title')}
          description={te('body')}
          action={<Button onClick={() => void refetch()}>{tc('retry')}</Button>}
        />
      ) : (data ?? []).length === 0 ? (
        <EmptyState
          illustration={<IlloCompass />}
          title={t('empty.title')}
          description={t('noSheets')}
        />
      ) : (
        <ul className="flex list-none flex-col gap-3 p-0">
          {(data ?? []).map((sheet) => (
            <li key={sheet.id}>
              <Panel>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <Link href={`/sheets/${sheet.id}`} className="font-bold">
                      {sheet.title}
                    </Link>
                    <p className="text-body-s text-ink-500">
                      {[
                        sheet.language.toUpperCase(),
                        t('itemCount', { count: sheet.items.length }),
                        fmt.date(sheet.created_at),
                      ].join(' · ')}
                    </p>
                  </div>
                  <Badge variant={sheet.rendered_at ? 'success' : 'neutral'}>
                    {sheet.rendered_at ? t('rendered') : t('draft')}
                  </Badge>
                </div>
              </Panel>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
