'use client';

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  IlloSlate,
  LoadingState,
  MasteryMeter,
  type MasteryBand,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';

import { Link } from '@/i18n/navigation';
import { useHome } from '@/lib/api/queries';
import { useFormatters } from '@/lib/format';
import { useBandLabels } from '@/lib/bands';

export default function HomePage() {
  const t = useTranslations('home');
  const tc = useTranslations('common');
  const tm = useTranslations('mastery');
  const te = useTranslations('errors.generic');
  const bandLabels = useBandLabels();
  const fmt = useFormatters();
  const { data, isLoading, isError, error, refetch } = useHome();

  if (isLoading) {
    return <LoadingState shape="cards" label={tc('loading')} rows={4} />;
  }

  if (isError) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        details={error instanceof Error ? error.message : undefined}
        action={<Button onClick={() => void refetch()}>{tc('retry')}</Button>}
      />
    );
  }

  const classes = data?.classes ?? [];

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-6">
        <h1>{t('title')}</h1>
        {data?.teacher ? (
          <p className="mt-1 text-ink-500">
            {t('greeting', { name: data.teacher.first_name })}
          </p>
        ) : null}
      </header>

      {classes.length === 0 ? (
        <EmptyState
          illustration={<IlloSlate />}
          title={t('empty.title')}
          description={t('empty.body')}
          action={
            <Link href="/classes">
              <Button variant="primary">{t('empty.action')}</Button>
            </Link>
          }
        />
      ) : (
        <ul className="grid list-none grid-cols-1 gap-4 p-0 lg:grid-cols-2">
          {classes.map((c) => {
            // The worst band with any cells in it — what the teacher should
            // look at first on this class.
            const worst = (['fading', 'weak', 'ok', 'solid'] as MasteryBand[]).find(
              (b) => (c.band_counts?.[b] ?? 0) > 0,
            );
            return (
              <li key={c.class_id}>
                <Card className="h-full">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h2 className="text-h2">
                        <Link
                          href={`/classes/${c.class_id}`}
                          className="text-ink-900 no-underline hover:text-primary-700"
                        >
                          {c.code}
                        </Link>
                      </h2>
                      {c.label ? <p className="text-body-s text-ink-500">{c.label}</p> : null}
                    </div>
                    <Badge>{t('students', { count: c.student_count })}</Badge>
                  </div>

                  <dl className="mt-4 grid grid-cols-1 gap-2 text-body-s sm:grid-cols-2">
                    <div>
                      <dt className="text-ink-500">{t('lastSheet')}</dt>
                      <dd className="font-bold">
                        {c.last_sheet_title ?? t('noSheetYet')}
                        {c.last_sheet_at ? (
                          <span className="ml-2 font-normal text-ink-500">
                            {fmt.date(c.last_sheet_at)}
                          </span>
                        ) : null}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-ink-500">{t('pendingCorrections', { count: 0 })}</dt>
                      <dd className="font-bold" data-numeric>
                        {t('pendingCorrections', { count: c.pending_scans })}
                      </dd>
                    </div>
                  </dl>

                  <p className="mt-3 text-body-s text-ink-700">
                    {t('needAttention', { count: c.students_needing_attention })}
                  </p>

                  {worst ? (
                    <div className="mt-3">
                      <MasteryMeter
                        band={worst}
                        score={null}
                        bandLabel={bandLabels[worst]}
                        caption={tm('attempts', { count: c.band_counts?.[worst] ?? 0 })}
                      />
                    </div>
                  ) : null}
                </Card>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
