'use client';

import {
  Badge,
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  IlloSlate,
  LoadingState,
  MasteryMeter,
  type MasteryBand,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';

import { Link } from '@/i18n/navigation';
import { useHome } from '@/lib/api/queries';
import { useFormatters } from '@/lib/format';
import { useBandLabels } from '@/lib/bands';

export default function HomePage() {
  const t = useTranslations('home');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const locale = useLocale();
  const bandLabels = useBandLabels();
  const fmt = useFormatters();
  const { data, isLoading, isError, refetch } = useHome();

  if (isLoading) {
    return <LoadingState shape="cards" label={tc('loading')} rows={4} />;
  }

  if (isError) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={<Button onClick={() => void refetch()}>{tc('retry')}</Button>}
      />
    );
  }

  const classes = data?.classes ?? [];
  const subjects = data?.subjects ?? [];

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-6">
        <h1>{t('title')}</h1>
        {data?.teacher ? (
          <p className="mt-1 text-ink-500">
            {t('greeting', { name: data.teacher.first_name })}
          </p>
        ) : null}

        {/* The subjects the teacher teaches. The API has always returned these
            and the screen never rendered them, so "classes and subjects" was
            only ever half true. Outline chips: official data is not coloured. */}
        {subjects.length > 0 ? (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-label text-ink-500">{t('subjects')}</span>
            {subjects.map((s) => (
              <Chip key={s.id}>{s.labels?.[locale] ?? s.labels?.fr ?? s.key}</Chip>
            ))}
          </div>
        ) : null}
      </header>

      {classes.length === 0 ? (
        <EmptyState
          illustration={<IlloSlate />}
          title={t('empty.title')}
          description={t('empty.body')}
          action={
            <Link href="/classes/new" className="ard-btn" data-variant="primary">
              {t('empty.action')}
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
                        {c.last_sheet_title ? (
                          // The overview names the teacher's most recent work;
                          // it has to be a way in, not a label. Reaching it used
                          // to mean remembering the URL.
                          <Link href={`/sheets?class=${c.class_id}`}>{c.last_sheet_title}</Link>
                        ) : (
                          t('noSheetYet')
                        )}
                        {c.last_sheet_at ? (
                          <span className="ml-2 font-normal text-ink-500">
                            {fmt.date(c.last_sheet_at)}
                          </span>
                        ) : null}
                      </dd>
                    </div>
                    <div>
                      {/* The term is the name of the stat. It used to be the
                          value string rendered with a hard-coded count of 0, so
                          a class with three pending scans read
                          "No corrections pending / 3 corrections pending". */}
                      <dt className="text-ink-500">{t('pendingCorrectionsLabel')}</dt>
                      <dd className="font-bold" data-numeric>
                        {c.pending_scans > 0 ? (
                          <Link href={`/scans?class=${c.class_id}`}>
                            {t('pendingCorrectionsValue', { count: c.pending_scans })}
                          </Link>
                        ) : (
                          t('pendingCorrectionsValue', { count: c.pending_scans })
                        )}
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
                        // `band_counts` counts (student x competency) CELLS in
                        // this band, not answers. Captioning it "23 answers"
                        // was off by a factor of 24 on the demo class and named
                        // the wrong quantity entirely.
                        caption={t('bandCells', { count: c.band_counts?.[worst] ?? 0 })}
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
