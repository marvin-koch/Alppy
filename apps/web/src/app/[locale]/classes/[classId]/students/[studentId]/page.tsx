'use client';

import {
  Button,
  Card,
  ConceptTag,
  ErrorState,
  LoadingState,
  MasteryCurve,
  MasteryMeter,
  Panel,
  ProgressRing,
  type MasteryBand,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { use } from 'react';

import { useStudentMastery } from '@/lib/api/queries';
import { useBandLabels } from '@/lib/bands';

export default function StudentPage({
  params,
}: {
  params: Promise<{ studentId: string }>;
}) {
  const { studentId } = use(params);
  const t = useTranslations('student');
  const tm = useTranslations('mastery');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const a11y = useTranslations('a11y');
  const locale = useLocale();
  const bandLabels = useBandLabels();

  const { data, isLoading, isError, refetch } = useStudentMastery(studentId);

  if (isLoading) return <LoadingState shape="profile" label={tc('loading')} />;
  if (isError || !data) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={<Button onClick={() => void refetch()}>{tc('retry')}</Button>}
      />
    );
  }

  const percent = Math.round((data.overall_score ?? 0) * 100);

  const section = (
    titleText: string,
    items: typeof data.strengths,
    emptyText: string,
  ) => (
    <Card>
      <h2 className="mb-3 text-h3">{titleText}</h2>
      {items.length === 0 ? (
        <p className="text-body-s text-ink-500">{emptyText}</p>
      ) : (
        <ul className="flex list-none flex-col gap-3 p-0">
          {items.map((item) => (
            <li key={item.competency.id} className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <ConceptTag code={item.competency.code} />
                <span className="text-body-s">
                  {item.competency.labels?.[locale] ?? item.competency.labels?.fr ?? ''}
                </span>
              </div>
              <MasteryMeter
                band={item.band as MasteryBand}
                score={item.score}
                bandLabel={bandLabels[item.band as MasteryBand]}
                caption={
                  item.provisional
                    ? tm('provisionalHelp')
                    : item.days_until_review === null
                      ? tm('attempts', { count: item.attempts_count })
                      : item.days_until_review === 0
                        ? tm('reviewOverdue')
                        : tm('reviewDue', { days: item.days_until_review })
                }
              />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6 flex flex-wrap items-center gap-4">
        <ProgressRing
          value={data.overall_score ?? 0}
          label={a11y('progressRing', { percent })}
          size={88}
        />
        <div>
          <h1>
            {data.student.first_name} {data.student.last_name}
          </h1>
          {/* The uid is what appears on paper and in every prompt; the teacher
              needs to be able to match a sheet to this page. */}
          <p className="mono text-body-s text-ink-500" data-numeric>
            {data.student.uid}
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {section(t('gaps'), data.gaps, t('noGaps'))}
        {section(t('strengths'), data.strengths, t('noStrengths'))}
      </div>

      {data.all_competencies.some((c) => c.history.length > 1) ? (
        <Panel className="mt-4">
          <h2 className="mb-3 text-h3">{t('trend')}</h2>
          <div className="flex flex-col gap-4">
            {data.all_competencies
              .filter((c) => c.history.length > 1)
              .slice(0, 6)
              .map((c) => (
                <div key={c.competency.id}>
                  <div className="mb-1 flex items-center gap-2">
                    <ConceptTag code={c.competency.code} />
                    <span className="text-body-s text-ink-500">
                      {c.competency.labels?.[locale] ?? c.competency.code}
                    </span>
                  </div>
                  <MasteryCurve
                    // The curve wants any monotonic x; the API sends ISO timestamps.
                    points={c.history.map((p) => ({ at: Date.parse(p.at), score: p.score }))}
                    label={t('trend')}
                  />
                </div>
              ))}
          </div>
        </Panel>
      ) : null}
    </div>
  );
}
