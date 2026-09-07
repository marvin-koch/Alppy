'use client';

import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  IlloCurve,
  LoadingState,
  MasteryLegend,
  MasteryMatrix,
  Select,
  type MasteryBand,
  type MasteryValue,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { use, useMemo, useState } from 'react';

import { CellDrillDown } from '@/components/CellDrillDown';
import { Link, useRouter } from '@/i18n/navigation';
import type { MatrixSort, Uuid } from '@/lib/api/types';
import { useChapters, useClass, useClassMastery, useStudents } from '@/lib/api/queries';
import { useScope } from '@/lib/scope';
import { useBandLabels, useBandHelp } from '@/lib/bands';

export default function ClassPage({
  params,
}: {
  params: Promise<{ classId: string }>;
}) {
  const { classId } = use(params);
  const t = useTranslations('classes');
  const tm = useTranslations('mastery');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const ts = useTranslations('sheets');
  const locale = useLocale();
  const bandLabels = useBandLabels();
  const bandHelp = useBandHelp();
  const router = useRouter();

  const [chapterId, setChapterId] = useState<Uuid | ''>('');
  const [sort, setSort] = useState<MatrixSort>('roster');
  // Which cell the drill-down is showing. Null closes it.
  const [drill, setDrill] = useState<{ studentId: Uuid; competencyId: Uuid } | null>(null);

  const klass = useClass(classId);
  const students = useStudents(classId);
  // The subject the whole app is scoped to, narrowed to the ones this class
  // actually has work in. Picking `subject_ids[0]` silently meant a class with
  // two subjects showed one of them with no way to see which.
  const scope = useScope();
  const subjectIds = klass.data?.subject_ids ?? [];
  const subjectId =
    scope.subjectId && subjectIds.includes(scope.subjectId)
      ? scope.subjectId
      : subjectIds[0];
  // Without a subject there is no chapter list to filter by. Asking anyway sent
  // `?subject_id=undefined` and filled the picker with every chapter in the
  // school.
  const chapters = useChapters(subjectId);
  const mastery = useClassMastery(classId, {
    ...(subjectId ? { subjectId } : {}),
    ...(chapterId ? { chapterId } : {}),
    sort,
  });

  // The matrix asks for a value per (student, competency); an index keeps that
  // lookup O(1) rather than scanning the cell list for every cell drawn.
  const cellIndex = useMemo(() => {
    const map = new Map<string, MasteryValue>();
    for (const cell of mastery.data?.cells ?? []) {
      map.set(`${cell.student_id}:${cell.competency_id}`, {
        band: cell.band as MasteryBand,
        // A never-assessed cell has no percentage. The API cannot send null
        // here (the field is not nullable), so the boundary is where the
        // distinction has to be restored — "not yet seen" is a band, not a 0.
        score: cell.band === 'none' ? null : cell.score,
      });
    }
    return map;
  }, [mastery.data]);

  const isLoading = klass.isLoading || students.isLoading || mastery.isLoading;
  const isError = klass.isError || students.isError || mastery.isError;

  if (isLoading) return <LoadingState shape="matrix" label={tc('loading')} rows={8} columns={7} />;

  if (isError) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={
          <Button
            onClick={() => {
              void klass.refetch();
              void students.refetch();
              void mastery.refetch();
            }}
          >
            {tc('retry')}
          </Button>
        }
      />
    );
  }

  const roster = students.data ?? [];
  const competencies = mastery.data?.competencies ?? [];
  const matrixStudents = mastery.data?.students ?? [];
  // The server owns the row order (roster or weakest-first); fall back to the
  // roster only before the first matrix response has landed.
  const rows = matrixStudents.length > 0 ? matrixStudents : roster;
  const isFiltered = chapterId !== '';

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1>{t('title', { code: klass.data?.code ?? '' })}</h1>
        <Link href="/sheets/new">
          <Button variant="primary">{ts('new')}</Button>
        </Link>
      </header>

      {roster.length === 0 ? (
        <EmptyState
          illustration={<IlloCurve />}
          title={t('empty.title')}
          description={t('empty.body')}
          // Was a bare <button> with no handler and no href: it rendered, it
          // took focus, and clicking it did nothing at all.
          action={
            <Link href={`/classes/${classId}/roster`} className="ard-btn" data-variant="primary">
              {t('empty.action')}
            </Link>
          }
        />
      ) : (
        <>
          {/* Filter and sort. Both live above the grid because they change what
              the grid *is*, not how one row reads.

              Card, not Panel: these sit directly on the page canvas, and a Card
              is the separate object while a Panel is a subdivision of one you
              are already inside. Using Panel here would be using it as a "less
              emphatic Card", which is the confusion CLAUDE.md forbids. */}
          <Card className="mb-4 flex flex-wrap items-end gap-4">
            <Field label={tm('filterChapter')}>
              <Select
                value={chapterId}
                onChange={(event) => setChapterId(event.target.value as Uuid | '')}
              >
                <option value="">{tm('allChapters')}</option>
                {(chapters.data ?? []).map((chapter) => (
                  <option key={chapter.id} value={chapter.id}>
                    {chapter.labels?.[locale] ?? chapter.labels?.fr ?? chapter.key}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={tm('sortBy')}>
              <Select
                value={sort}
                onChange={(event) => setSort(event.target.value as MatrixSort)}
              >
                <option value="roster">{tm('sortRoster')}</option>
                <option value="weakest">{tm('sortWeakest')}</option>
              </Select>
            </Field>
          </Card>

          {competencies.length === 0 ? (
            <EmptyState
              illustration={<IlloCurve />}
              title={isFiltered ? tm('emptyChapter.title') : tm('empty.title')}
              description={isFiltered ? tm('emptyChapter.body') : tm('empty.body')}
              action={
                isFiltered ? (
                  <Button onClick={() => setChapterId('')}>{tm('emptyChapter.action')}</Button>
                ) : (
                  <Link href="/sheets/new">
                    <Button variant="primary">{tm('empty.action')}</Button>
                  </Link>
                )
              }
            />
          ) : null}

          {/* The legend carries the same three channels the cells do — tint,
              glyph and word — or it explains nothing. It stays on the page even
              when the grid is empty, so the vocabulary is always available. */}
          <Card className="mb-4">
            <h2 className="mb-2 text-label text-ink-500">{tm('legend')}</h2>
            <MasteryLegend bandLabels={bandLabels} bandHelp={bandHelp} />
          </Card>

          {competencies.length > 0 ? (
            <Card flush>
              <MasteryMatrix
                students={rows.map((s) => ({
                  id: s.id,
                  firstName: s.first_name,
                  lastName: s.last_name,
                }))}
                competencies={competencies.map((c) => ({
                  id: c.id,
                  code: c.code,
                  // Curriculum wording is authoritative in its own language;
                  // fall back to French (the default locale) and then the code.
                  label: c.labels?.[locale] ?? c.labels?.fr ?? c.code,
                }))}
                valueFor={(studentId, competencyId) =>
                  cellIndex.get(`${studentId}:${competencyId}`)
                }
                bandLabels={bandLabels}
                // The accessible name is a translated sentence, not a list
                // joined with punctuation: the library's fallback hard-codes
                // " · " and a French-spaced " %", which is wrong in English.
                formatLabel={({ studentName, competencyLabel, bandLabel, score, hasScore }) =>
                  hasScore && score !== null
                    ? tm('cellLabel', {
                        student: studentName,
                        competency: competencyLabel,
                        band: bandLabel,
                        percent: Math.round(score * 100),
                      })
                    : tm('cellLabelNotAssessed', {
                        student: studentName,
                        competency: competencyLabel,
                        band: bandLabel,
                      })
                }
                caption={t('matrix')}
                studentColumnLabel={t('roster')}
                // A coloured cell must not be the only way to reach a profile:
                // a class with nothing assessed yet has no cells at all.
                renderStudentName={(student, name) => (
                  <Link
                    href={`/classes/${classId}/students/${student.id}`}
                    className="text-ink-900 no-underline hover:underline"
                  >
                    {name}
                  </Link>
                )}
                selectedCellId={drill ? `${drill.studentId}:${drill.competencyId}` : undefined}
                onCellSelect={({ studentId, competencyId }) =>
                  setDrill({ studentId: studentId as Uuid, competencyId: competencyId as Uuid })
                }
                bleed
              />
            </Card>
          ) : null}
        </>
      )}

      {drill ? (
        <CellDrillDown
          studentId={drill.studentId}
          competencyId={drill.competencyId}
          onClose={() => setDrill(null)}
          onOpenProfile={() => {
            router.push(`/classes/${classId}/students/${drill.studentId}`);
            setDrill(null);
          }}
        />
      ) : null}
    </div>
  );
}
