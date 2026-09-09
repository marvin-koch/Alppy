'use client';

import {
  Breadcrumb,
  Button,
  Card,
  Chip,
  ConceptTag,
  MasteryBandTag,
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
import { use, useMemo } from 'react';

import { Link } from '@/i18n/navigation';
import { useClass, useCurriculumTree, useStudentMastery } from '@/lib/api/queries';
import type { SheetTakenOut, Uuid } from '@/lib/api/types';
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
  const tt = useTranslations('tree');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const a11y = useTranslations('a11y');
  const tstud = useTranslations('students');
  const locale = useLocale();
  const fmt = useFormatters();
  const bandLabels = useBandLabels();

  const { data, isLoading, isError, refetch } = useStudentMastery(studentId);
  const klass = useClass(classId as Uuid);
  // The same tree the class dashboard shows, narrowed to this child, so the
  // headings carry their own bands rather than the class's.
  const tree = useCurriculumTree(classId, { studentId });


  // Group the history by the Theme each sheet is filed under. The tree is
  // already fetched for the gaps/strengths headings, so the labels cost
  // nothing extra; a sheet whose Theme is not in this Branch — or which sits
  // in `unfiled` — falls into one honest "other" group rather than being
  // hidden or given a guessed heading.
  const sheetGroups = useMemo(() => {
    const themeLabel = new Map<string, string>();
    for (const b of tree.data?.branches ?? []) {
      for (const competence of b.competences) {
        for (const theme of competence.themes) {
          themeLabel.set(
            theme.chapter_id,
            theme.labels?.[locale] ?? theme.labels?.fr ?? theme.key,
          );
        }
      }
    }
    const order: string[] = [];
    const bucket = new Map<string, SheetTakenOut[]>();
    for (const sheet of data?.sheets ?? []) {
      const key = sheet.chapter_id ?? 'unfiled';
      if (!bucket.has(key)) {
        bucket.set(key, []);
        order.push(key);
      }
      bucket.get(key)?.push(sheet);
    }
    return order.map((key) => ({
      key,
      label: themeLabel.get(key) ?? tt('unfiled'),
      sheets: bucket.get(key) ?? [],
    }));
  }, [data?.sheets, tree.data, locale, tt]);

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
      {/* A route back up, not just back one: from a pupil you often want the
          class, and from the class the roster. A single "retour" link could
          only ever offer the nearest of those. */}
      <Breadcrumb
        className="mb-3"
        label={a11y('breadcrumb')}
        items={[
          {
            label: klass.data?.code ?? '',
            href: `/classes/${classId}`,
            key: 'class',
          },
          {
            label: tstud('title'),
            href: `/classes/${classId}/students`,
            key: 'roster',
          },
          {
            label: `${data.student.first_name} ${data.student.last_name}`.trim(),
            key: 'student',
          },
        ]}
        renderLink={(item, children) => <Link href={item.href!}>{children}</Link>}
      />

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
              needs to be able to match a sheet to this page.

              The class chips sit beside it and only when there is more than
              one: a pupil who sits in a single class does not need to be told
              which. When there ARE two, the first is the home — the class that
              minted this identifier, which is why a 9A code can head a 7B
              roster (D69). */}
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-body-s text-ink-500" data-numeric>
              {data.student.uid}
            </span>
            {data.student.class_codes.length > 1
              ? data.student.class_codes.map((code) => (
                  <Chip
                    key={code}
                    variant={code === data.student.home_class_code ? 'primary' : 'neutral'}
                  >
                    {code === data.student.home_class_code
                      ? tstud('homeClass', { code })
                      : code}
                  </Chip>
                ))
              : null}
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

          {/* Which papers produced all this, grouped by the Theme each sheet
              is FILED under — the teacher's own filing, never one inferred
              from the items (I-sheets-11). A term reads as three or four
              teaching units instead of a flat list of twelve papers.

              Every row carries the pupil's band ON THAT SHEET: a roll-up of
              the sheet's competencies, not a mean of its items
              (I-mastery-11) — and the mark beside it stays a mark, because a
              barème and a band are two different quantities. */}
          <Card className="mt-4">
            <h2 className="mb-3 text-h3">{t('history')}</h2>
            {data.sheets.length === 0 ? (
              <p className="text-body-s text-ink-500">{t('noSheets')}</p>
            ) : (
              <div className="flex flex-col gap-5">
                {sheetGroups.map((group) => (
                  <section key={group.key}>
                    <h3 className="mb-2 flex flex-wrap items-baseline gap-2 text-body-s font-bold text-ink-700">
                      {group.label}
                      <span className="font-normal text-ink-500">
                        {tt('sheetCount', { count: group.sheets.length })}
                      </span>
                    </h3>
                    <ul className="flex list-none flex-col gap-2 p-0">
                      {group.sheets.map((sheet) => (
                        <li
                          key={sheet.sheet_id}
                          className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-2 last:border-0"
                        >
                          <span className="flex min-w-0 flex-col gap-0.5">
                            {/* The pupil's OWN copy, not the class-wide sheet:
                                from a profile, "this sheet" means the paper
                                they sat. */}
                            <Link
                              href={`/classes/${classId}/students/${studentId}/sheets/${sheet.sheet_id}`}
                            >
                              {sheet.title}
                            </Link>
                            <span className="flex flex-wrap items-baseline gap-3 text-body-s text-ink-500">
                              <time data-numeric>{fmt.date(sheet.answered_at)}</time>
                              <span data-numeric>
                                {t('sheetScore', {
                                  correct: sheet.correct_count,
                                  total: sheet.attempts_count,
                                })}
                              </span>
                              {sheet.scan_id ? (
                                <Link href={`/scans/${sheet.scan_id}`}>
                                  {t('openScan')}
                                </Link>
                              ) : (
                                <span>{t('notScanned')}</span>
                              )}
                            </span>
                          </span>
                          {sheet.mastery ? (
                            <MasteryBandTag
                              band={sheet.mastery.band as MasteryBand}
                              label={bandLabels[sheet.mastery.band as MasteryBand]}
                              // Coverage only when it is INCOMPLETE: "2 sur 2"
                              // says nothing the band does not (DC-content-07).
                              caption={
                                sheet.mastery.child_count > 0 &&
                                sheet.mastery.assessed_count < sheet.mastery.child_count
                                  ? tm('coverage', {
                                      assessed: sheet.mastery.assessed_count,
                                      total: sheet.mastery.child_count,
                                    })
                                  : undefined
                              }
                            />
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
