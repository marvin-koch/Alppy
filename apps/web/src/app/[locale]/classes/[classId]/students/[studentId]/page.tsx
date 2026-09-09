'use client';

import {
  Button,
  Card,
  ConceptTag,
  EmptyState,
  ErrorState,
  IlloCurve,
  LoadingState,
  MasteryCurve,
  MasteryMeter,
  ProgressRing,
  type MasteryBand,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { use } from 'react';

import { Link } from '@/i18n/navigation';
import { useCurriculumTree, useStudentMastery } from '@/lib/api/queries';
import { useBandLabels } from '@/lib/bands';
import { useFormatters } from '@/lib/format';

/** The same thresholds as docs/mastery-model.md §2, for the overall ring. */
function bandOf(score: number): MasteryBand {
  if (score >= 0.9) return 'solid';
  if (score >= 0.75) return 'ok';
  if (score >= 0.6) return 'weak';
  return 'fading';
}

export default function StudentPage({
  params,
}: {
  params: Promise<{ classId: string; studentId: string }>;
}) {
  const { classId, studentId } = use(params);
  const t = useTranslations('student');
  const tm = useTranslations('mastery');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const a11y = useTranslations('a11y');
  const locale = useLocale();
  const fmt = useFormatters();
  const bandLabels = useBandLabels();

  const { data, isLoading, isError, refetch } = useStudentMastery(studentId);
  // The same tree the class dashboard shows, narrowed to this child, so the
  // headings carry their own bands rather than the class's.
  const tree = useCurriculumTree(classId, { studentId });

  if (isLoading || tree.isLoading) return <LoadingState shape="profile" label={tc('loading')} />;
  if (isError || !data) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={<Button onClick={() => void refetch()}>{tc('retry')}</Button>}
      />
    );
  }

  const assessed = data.all_competencies.length > 0;
  const percent = Math.round((data.overall_score ?? 0) * 100);
  const overallBand = assessed ? bandOf(data.overall_score ?? 0) : 'none';

  /**
   * Group a flat competency list under the Competence and Theme it belongs to.
   *
   * The tree is read for THIS student (`studentId`), so the headings carry the
   * child's own rolled-up bands rather than the class's. A competency the tree
   * does not place — an exercise tagged with a code no chapter claims — keeps
   * its own group at the end rather than disappearing, the same rule the
   * builder's untagged bucket follows.
   */
  const groups = (items: typeof data.strengths) => {
    const placement = new Map<string, { competence: string; theme: string }>();
    for (const branch of tree.data?.branches ?? []) {
      for (const competence of branch.competences) {
        const competenceLabel = `${competence.code} · ${
          competence.labels?.[locale] ?? competence.labels?.fr ?? competence.code
        }`;
        for (const theme of competence.themes) {
          const themeLabel = theme.labels?.[locale] ?? theme.labels?.fr ?? theme.key;
          for (const id of theme.competency_ids ?? []) {
            placement.set(id, { competence: competenceLabel, theme: themeLabel });
          }
        }
      }
    }
    const out = new Map<string, { competence: string; theme: string; items: typeof items }>();
    for (const item of items) {
      const at = placement.get(item.competency.id);
      const key = at ? `${at.competence}\u0000${at.theme}` : '';
      const bucket = out.get(key);
      if (bucket) bucket.items.push(item);
      else
        out.set(key, {
          competence: at?.competence ?? '',
          theme: at?.theme ?? '',
          items: [item],
        });
    }
    return [...out.values()];
  };

  const section = (
    titleText: string,
    items: typeof data.strengths,
    emptyText: string,
  ) => (
    <Card>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-h3">{titleText}</h2>
        <p className="text-body-s text-ink-500">{t('byCompetence')}</p>
      </div>
      {items.length === 0 ? (
        <p className="text-body-s text-ink-500">{emptyText}</p>
      ) : (
        groups(items).map((group) => (
          <section
            key={`${group.competence}-${group.theme}`}
            className="mb-4 flex flex-col gap-2 last:mb-0"
          >
            {/* Headings, not nested Cards: these are subdivisions of the card
                they sit in (DC-shape-01). */}
            {group.competence ? (
              <h3 className="border-b border-line pb-1 text-body-s font-bold text-ink-700">
                {group.competence}
              </h3>
            ) : null}
            {group.theme ? (
              <h4 className="text-label text-ink-500">{group.theme}</h4>
            ) : null}
        <ul className="flex list-none flex-col gap-3 p-0">
          {group.items.map((item) => (
            <li key={item.competency.id} className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <ConceptTag code={item.competency.code} />
                <span className="text-body-s">
                  {item.competency.labels?.[locale] ?? item.competency.labels?.fr ?? ''}
                </span>
              </div>
              <MasteryMeter
                band={item.band as MasteryBand}
                score={item.band === 'none' ? null : item.score}
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
          </section>
        ))
      )}
    </Card>
  );

  return (
    <div className="mx-auto max-w-4xl">
      <p className="mb-3 text-body-s">
        <Link href={`/classes/${classId}`}>{t('backToClass')}</Link>
      </p>

      <header className="mb-6 flex flex-wrap items-center gap-4">
        {/* The ring carries the band, not the action violet: it is a reading of
            the student, not something to click. `centre` supplies the unit,
            because a bare "90" is a number without a quantity — and a student
            with nothing assessed shows a dash, never a zero.

            The label sits under the ring, not in `centreCaption`: at 88px the
            centre fits a percentage and nothing else, and "Score global" wrapped
            to two lines and spilled outside the stroke. */}
        <div className="flex flex-col items-center gap-1">
          <ProgressRing
            value={assessed ? (data.overall_score ?? 0) : 0}
            band={overallBand}
            centre={assessed ? fmt.percent(data.overall_score ?? 0) : '—'}
            label={assessed ? a11y('progressRing', { percent }) : tm('band.none')}
            size={88}
          />
          <span className="text-label text-ink-500">{t('overall')}</span>
        </div>
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

      {!assessed ? (
        <EmptyState
          illustration={<IlloCurve />}
          title={t('notAssessed.title')}
          description={t('notAssessed.body')}
          action={
            <Link href="/sheets/new">
              <Button variant="primary">{tm('empty.action')}</Button>
            </Link>
          }
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {section(t('gaps'), data.gaps, t('noGaps'))}
            {section(t('strengths'), data.strengths, t('noStrengths'))}
          </div>

          {/* A sibling of the two Cards above, holding the same kind of content
              region — so it is a Card too. Three peers, one shape. */}
          {data.all_competencies.some((c) => c.history.length > 1) ? (
            <Card className="mt-4">
              <h2 className="mb-3 text-h3">{t('trend')}</h2>
              {/* Two columns from `lg`: a curve is ~320px wide at its natural
                  aspect, so one per row leaves half the panel empty. */}
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
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
                        description={t('trendDescription', {
                          competency: c.competency.code,
                          from: fmt.percent(c.history[0]?.score ?? 0),
                          to: fmt.percent(c.history[c.history.length - 1]?.score ?? 0),
                          since: fmt.date(c.history[0]?.at),
                        })}
                      />
                    </div>
                  ))}
              </div>
            </Card>
          ) : null}

          {/* Which papers produced all this. Every row is a route back to the
              sheet and, when there is one, to the scan it was read from. */}
          <Card className="mt-4">
            <h2 className="mb-3 text-h3">{t('history')}</h2>
            {data.sheets.length === 0 ? (
              <p className="text-body-s text-ink-500">{t('noSheets')}</p>
            ) : (
              <ul className="flex list-none flex-col gap-2 p-0">
                {data.sheets.map((sheet) => (
                  <li
                    key={sheet.sheet_id}
                    className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-2 last:border-0"
                  >
                    <span className="flex flex-wrap items-baseline gap-2">
                      {/* The pupil's OWN copy, not the class-wide sheet: from a
                          profile, "this sheet" means the paper they sat. */}
                      <Link
                        href={`/classes/${classId}/students/${studentId}/sheets/${sheet.sheet_id}`}
                      >
                        {sheet.title}
                      </Link>
                      <time className="text-body-s text-ink-500" data-numeric>
                        {fmt.date(sheet.answered_at)}
                      </time>
                    </span>
                    <span className="flex flex-wrap items-baseline gap-3 text-body-s text-ink-500">
                      <span data-numeric>
                        {t('sheetScore', {
                          correct: sheet.correct_count,
                          total: sheet.attempts_count,
                        })}
                      </span>
                      {sheet.scan_id ? (
                        <Link href={`/scans/${sheet.scan_id}`}>{t('openScan')}</Link>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
