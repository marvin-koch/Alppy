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
  BandHistogram,
  type MasteryBand,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';

import { Link } from '@/i18n/navigation';
import { useHome } from '@/lib/api/queries';
import { requestIdOf } from '@/lib/api/error-message';
import { useFormatters } from '@/lib/format';
import { useBandLabels } from '@/lib/bands';

export default function HomePage() {
  const t = useTranslations('home');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const locale = useLocale();
  const bandLabels = useBandLabels();
  const tstud = useTranslations('students');
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
        requestId={requestIdOf(error)}
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
          <p className="mt-1 text-ink-500">{t('greeting', { name: data.teacher.first_name })}</p>
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
            return (
              <li key={c.class_id}>
                <Card className="h-full">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h2 className="text-h2">
                        <Link
                          href={`/classes/${c.class_id}`}
                          // A chip is small; the thing a thumb aims at is not.
                          className="inline-flex min-h-11 items-center gap-2 text-ink-900 no-underline hover:text-primary-700"
                        >
                          <span className="rounded-sm bg-primary-100 px-2 py-0.5 text-h3 text-primary-700">
                            {c.code}
                          </span>
                        </Link>
                      </h2>
                      {c.label ? <p className="text-body-s text-ink-500">{c.label}</p> : null}
                    </div>
                    <Badge>{t('students', { count: c.student_count })}</Badge>
                  </div>

                  <p className="mt-3 text-body-s">
                    <span className="text-ink-500">{t('lastSheet')} : </span>
                    {c.last_sheet_title ? (
                      // The overview names the teacher's most recent work; it
                      // has to be a way in, not a label.
                      <Link href={`/sheets?class=${c.class_id}`}>{c.last_sheet_title}</Link>
                    ) : (
                      <span className="text-ink-500">{t('noSheetYet')}</span>
                    )}
                    {c.last_sheet_at ? (
                      <span className="ml-2 text-ink-500">{fmt.date(c.last_sheet_at)}</span>
                    ) : null}
                  </p>

                  {/* The SHAPE of the class, not its average. This card used to
                      show only the worst band, which on a real roster is
                      "S'efface" for every class — a constant, not a signal. */}
                  <BandHistogram
                    className="mt-4"
                    counts={c.band_counts as Partial<Record<MasteryBand, number>>}
                    labels={bandLabels}
                    label={t('shapeLabel', { code: c.code })}
                  />

                  {/* Four routes into what the class actually needs. Before
                      these, the roster, the programme and the new detail pages
                      were reachable only by remembering a URL. */}
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Link
                      href={`/classes/${c.class_id}/students`}
                      className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 text-body-s font-semibold text-ink-900 no-underline hover:bg-primary-050"
                    >
                      {tstud('title')}
                      <span className="text-ink-500" data-numeric>
                        {c.student_count}
                      </span>
                    </Link>
                    <Link
                      href={`/classes/${c.class_id}`}
                      className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 text-body-s font-semibold text-ink-900 no-underline hover:bg-primary-050"
                    >
                      {t('actionAttention')}
                      {c.students_needing_attention > 0 ? (
                        <span
                          className="rounded-pill bg-danger-100 px-2 text-label font-bold text-danger-600"
                          data-numeric
                        >
                          {c.students_needing_attention}
                        </span>
                      ) : (
                        <span className="text-ink-500" data-numeric>
                          0
                        </span>
                      )}
                    </Link>
                    <Link
                      href={`/scans?class=${c.class_id}`}
                      className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 text-body-s font-semibold text-ink-900 no-underline hover:bg-primary-050"
                    >
                      {t('actionScans')}
                      {c.pending_scans > 0 ? (
                        <span
                          className="rounded-pill bg-danger-100 px-2 text-label font-bold text-danger-600"
                          data-numeric
                        >
                          {c.pending_scans}
                        </span>
                      ) : (
                        <span className="text-ink-500" data-numeric>
                          0
                        </span>
                      )}
                    </Link>
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      {classes.length > 0 ? (
        <p className="mt-5 px-1 text-body-s text-ink-500">{t('shapeHelp')}</p>
      ) : null}
    </div>
  );
}
