'use client';

import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  IconChevronRight,
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
import { CompetenceThemeFilter } from '@/components/CompetenceThemeFilter';
import { CurriculumTree } from '@/components/CurriculumTree';
import { Link, useRouter } from '@/i18n/navigation';
import type { MatrixSort, Uuid } from '@/lib/api/types';
import {
  useClass,
  useClassMastery,
  useCurriculumTree,
  useStudents,
} from '@/lib/api/queries';
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
  const tt = useTranslations('tree');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const ts = useTranslations('sheets');
  const locale = useLocale();
  const bandLabels = useBandLabels();
  const bandHelp = useBandHelp();
  const router = useRouter();

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
  // Competence and Theme come from the URL (`?competency=&chapter=`), so a
  // teacher can send a colleague a link to exactly this view. They are NOT
  // resolved to "the first one" the way class and subject are — see scope.tsx.
  const { competencyId, chapterId, setCompetency, setChapter } = scope;
  const tree = useCurriculumTree(classId, subjectId ? { subjectId } : {});
  const branch =
    tree.data?.branches.find((b) => b.subject_id === subjectId) ?? null;

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
  const isFiltered = chapterId !== null || competencyId !== null;

  const crumbLabel = (labels: Record<string, string> | undefined, fallback: string) =>
    labels?.[locale] ?? labels?.fr ?? fallback;
  const crumbCompetence = branch?.competences.find(
    (c) => c.competency_id === competencyId,
  );
  const crumbTheme = (branch?.competences ?? [])
    .flatMap((c) => c.themes)
    .find((t) => t.chapter_id === chapterId);
  const crumbs = [
    ...(branch ? [crumbLabel(branch.labels, branch.subject_key)] : []),
    ...(crumbCompetence ? [crumbCompetence.code] : []),
    ...(crumbTheme ? [crumbLabel(crumbTheme.labels, crumbTheme.key)] : []),
  ];

  return (
    <div className="mx-auto max-w-6xl">
      {/* Where you are in the programme, in words. The hierarchy is carried by
          `?competency=&chapter=` rather than by path segments, so without this
          the only thing naming your position is a pair of selects. */}
      <nav aria-label={tt('title')} className="mb-2 flex flex-wrap items-center gap-1.5 text-body-s font-semibold text-ink-500">
        <span>{klass.data?.code ?? ''}</span>
        {crumbs.map((crumb) => (
          <span key={crumb} className="flex items-center gap-1.5">
            <IconChevronRight size={14} aria-hidden className="text-ink-300" />
            <span className="last:text-ink-900">{crumb}</span>
          </span>
        ))}
      </nav>

      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
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
          <Card className="mb-4 flex flex-wrap items-end gap-4 py-4">
            <CompetenceThemeFilter
              classId={classId}
              subjectId={subjectId}
              competencyId={competencyId}
              chapterId={chapterId}
              onCompetencyChange={setCompetency}
              onChapterChange={setChapter}
            />
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
              title={isFiltered ? tm('emptyScope.title') : tm('empty.title')}
              description={isFiltered ? tm('emptyScope.body') : tm('empty.body')}
              action={
                isFiltered ? (
                  <Button
                    onClick={() => {
                      setCompetency(null);
                      setChapter(null);
                    }}
                  >
                    {tm('emptyScope.action')}
                  </Button>
                ) : (
                  <Link href="/sheets/new">
                    <Button variant="primary">{tm('empty.action')}</Button>
                  </Link>
                )
              }
            />
          ) : null}

          {/* The tree beside the grid: the programme on the left, this
              class's answers on the right. Stacks on a phone, where the tree
              becomes the drill-down and the matrix scrolls under it. */}
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
            <div className="lg:w-[22rem] lg:shrink-0">
              <CurriculumTree
                branch={branch}
                chapterId={chapterId}
                onSelectTheme={setChapter}
                isLoading={tree.isLoading}
              />
            </div>
            <div className="min-w-0 flex-1">
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
            </div>
          </div>

          {/* Below the grid, not above it: the legend explains the marks, so it
              costs nothing to read second, and a full-width card above the fold
              pushed the grid itself off the screen.

              Outside the matrix card on purpose. It stays on the page when the
              grid is empty, which is exactly when a teacher has not yet learnt
              the vocabulary (`mastery.spec.ts::a student with no attempts is
              not shown as a zero`). */}
          <Card className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 py-4">
            <h2 className="text-label text-ink-500">{tm('legend')}</h2>
            <MasteryLegend bandLabels={bandLabels} bandHelp={bandHelp} />
          </Card>
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
