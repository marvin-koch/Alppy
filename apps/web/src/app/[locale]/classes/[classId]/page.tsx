'use client';

import {
  Breadcrumb,
  Button,
  Card,
  EmptyState,
  ErrorState,
  IlloCurve,
  IconChevronDown,
  LoadingState,
  MasteryLegend,
  MasteryMatrix,
  SelectSurface,
  type BreadcrumbItem,
  type MasteryBand,
  type MasteryValue,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { use, useEffect, useMemo, useState } from 'react';

import { CellDrillDown } from '@/components/CellDrillDown';
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
import { useClassSubject } from '@/lib/use-class-subject';
import { useBandLabels, useBandHelp } from '@/lib/bands';
import { studentNameParts } from '@/lib/studentName';

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
  const ta = useTranslations('a11y');
  const tstud = useTranslations('students');
  const tteach = useTranslations('teaching');
  const ts = useTranslations('sheets');
  const tn = useTranslations('nav');
  const ttree = useTranslations('tree');
  const locale = useLocale();
  const bandLabels = useBandLabels();
  const bandHelp = useBandHelp();
  const router = useRouter();

  const [sort, setSort] = useState<MatrixSort>('roster');
  // Which cell the drill-down is showing. Null closes it.
  const [drill, setDrill] = useState<{ studentId: Uuid; competencyId: Uuid } | null>(null);

  const klass = useClass(classId);
  const students = useStudents(classId);
  // The Branch to read this class through. One hook, because three screens
  // each carried their own copy of the fallback and co-teaching turns that
  // edge case into the everyday one (D73).
  const scope = useScope();
  const { subjectId, choices } = useClassSubject(klass.data);
  // Competence and Theme come from the URL (`?competency=&chapter=`), so a
  // teacher can send a colleague a link to exactly this view. They are NOT
  // resolved to "the first one" the way class and subject are — see scope.tsx.
  const { competencyId, chapterId, setCompetency, setChapter } = scope;
  const tree = useCurriculumTree(classId, subjectId ? { subjectId } : {});
  const branch =
    tree.data?.branches.find((b) => b.subject_id === subjectId) ?? null;

  // A stale id from the URL degrades to "everything", never to an arbitrary
  // node. `scope` deliberately does not validate these — it has no tree — so
  // the component that fetched one is the one that can. This guard used to
  // live inside `CompetenceThemeFilter`; it outlived the filter, because a
  // shared link whose theme has since been renamed away must not silently
  // return an empty matrix.
  useEffect(() => {
    if (tree.isLoading || !branch) return;
    const competences = branch.competences;
    if (competencyId && !competences.some((c) => c.competency_id === competencyId)) {
      setCompetency(null);
      return;
    }
    const themes = competences.flatMap((c) => c.themes);
    if (chapterId && !themes.some((t) => t.chapter_id === chapterId)) {
      setChapter(null);
    }
  }, [tree.isLoading, branch, competencyId, chapterId, setCompetency, setChapter]);

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
  // The hierarchy lives in `?competency=&chapter=`, not in path segments, so a
  // crumb goes "up" by dropping the narrower parameter rather than by
  // navigating. The last crumb is where you already are and carries no href.
  const crumbs: BreadcrumbItem[] = [
    { label: klass.data?.code ?? '', key: 'class' },
    ...(branch
      ? [{ label: crumbLabel(branch.labels, branch.subject_key), key: 'branch' }]
      : []),
    ...(crumbCompetence ? [{ label: crumbCompetence.code, key: 'competence' }] : []),
    ...(crumbTheme
      ? [{ label: crumbLabel(crumbTheme.labels, crumbTheme.key), key: 'theme' }]
      : []),
  ];

  return (
    <div className="mx-auto max-w-6xl">
      {/* Where you are in the programme, in words. Without it the only thing
          naming your position is a pair of selects. */}
      <Breadcrumb items={crumbs} label={ta('breadcrumb')} className="mb-2" />

      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1>{t('title', { code: klass.data?.code ?? '' })}</h1>
        <div className="flex flex-wrap items-center gap-2">
          <Link href={`/classes/${classId}/students`}>
            <Button variant="secondary">{tstud('title')}</Button>
          </Link>
          {/* Reachable from the class it is about. It shows what the class
              STUDIES, which is a superset of the branches in the switcher
              above — so it is the one place a branch nobody teaches, or a
              colleague who should be on one, can be seen (D75). */}
          <Link href={`/classes/${classId}/teaching`}>
            <Button variant="secondary">{tteach('title')}</Button>
          </Link>
          <Link href="/sheets/new">
            <Button variant="primary">{ts('new')}</Button>
          </Link>
        </div>
      </header>

      {/* Two Branches in one class is ordinary now (D73): Camille takes maths
          AND French in 7B. Without this the only way to say WHICH one the
          page is showing was the rail, and the breadcrumb named it without
          offering to change it. One control, only when it is a real choice —
          a select with one option is furniture, and the crumb already says
          where you are. */}
      {choices.length > 1 ? (
        <div className="mb-4 max-w-xs">
          <SelectSurface
            label={tn('switchSubject')}
            value={subjectId ?? ''}
            onChange={(value) => scope.setSubject(value as Uuid)}
            options={scope.subjects.map((subject) => ({
              value: subject.id,
              label: crumbLabel(subject.labels, subject.key),
            }))}
          >
            <span className="flex min-h-11 items-center gap-2 rounded-md border border-line bg-surface px-3">
              <span className="text-label font-semibold uppercase tracking-label text-ink-500">
                {ttree('branch')}
              </span>
              <span className="min-w-0 flex-1 truncate text-body-s font-semibold text-ink-900">
                {branch ? crumbLabel(branch.labels, branch.subject_key) : ''}
              </span>
              <IconChevronDown size={16} className="shrink-0 text-ink-500" />
            </span>
          </SelectSurface>
        </div>
      ) : null}

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
          {/* Sort sits on the canvas, not in a Card of its own. It shared that
              Card with the Competence and Theme filters until the tree took
              those over; one select left alone in a full-width Card reads as a
              section that lost its contents. A Card is a separate OBJECT
              (DC-shape-01), and a single control is not one. */}
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <SelectSurface
              className="w-full rounded-md sm:w-64"
              label={tm('sortBy')}
              value={sort}
              onChange={(value) => setSort(value as MatrixSort)}
              options={[
                { value: 'roster', label: tm('sortRoster') },
                { value: 'weakest', label: tm('sortWeakest') },
              ]}
            >
              <span className="flex min-h-11 items-center gap-2 rounded-md border border-line bg-surface px-3">
                <span className="shrink-0 text-body-s text-ink-500">{tm('sortBy')}</span>
                <span className="min-w-0 flex-1 truncate text-body-s font-semibold">
                  {sort === 'weakest' ? tm('sortWeakest') : tm('sortRoster')}
                </span>
                <IconChevronDown size={16} className="shrink-0 text-ink-500" />
              </span>
            </SelectSurface>
          </div>

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
                basePath={`/classes/${classId}`}
                competencyId={competencyId}
                onSelectCompetence={setCompetency}
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
                  ...studentNameParts(s),
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
