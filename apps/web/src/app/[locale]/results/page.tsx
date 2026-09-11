'use client';

import {
  Card,
  EmptyState,
  ErrorState,
  Button,
  IconChevronRight,
  IlloCurve,
  LoadingState,
  PointsMatrix,
  ProgressRing,
  type PointsValue,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useMemo } from 'react';

import { Link, useRouter } from '@/i18n/navigation';
import { useClassPoints, useStudents } from '@/lib/api/queries';
import { useFormatters } from '@/lib/format';
import { aggregatePoints, pointsRatio, type PointsSummary } from '@/lib/points';
import { CompetenceThemeFilter } from '@/components/CompetenceThemeFilter';
import { useScope } from '@/lib/scope';
import { RevealNames } from '@/components/RevealNames';
import { useDiscretion } from '@/lib/discreet';
import { studentNameParts } from '@/lib/studentName';

/** The synthetic right-hand column: everything so far, added up. */
const TOTAL_COLUMN = '__total__';

/**
 * What the class actually scored.
 *
 * Deliberately a different screen from the mastery matrix, not a tab inside it.
 * A band is decayed evidence about a competency; a score is what the teacher's
 * barème says the paper was worth. They answer different questions — "does this
 * child understand fractions?" versus "what goes on the report?" — and a
 * teacher reading one for the other is exactly the confusion worth preventing.
 *
 * The rule that shapes every number here: an ungraded copy shows a dash, never
 * a zero. A term with two of five sheets marked is not three failures.
 */
export default function ResultsPage() {
  const t = useTranslations('results');
  const { hideNames } = useDiscretion();
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const fmt = useFormatters();
  const { classId, subjectId, currentClass, competencyId, chapterId, setCompetency, setChapter } =
    useScope();
  const router = useRouter();

  const points = useClassPoints(classId, {
    ...(subjectId ? { subjectId } : {}),
    ...(chapterId ? { chapterId } : {}),
  });
  const students = useStudents(classId);

  const byStudent = useMemo(() => {
    const index = new Map<string, PointsSummary>();
    for (const row of points.data?.students ?? []) {
      index.set(row.student_id, { earned: row.points_earned, possible: row.points_possible });
    }
    return index;
  }, [points.data]);

  const byCell = useMemo(() => {
    const index = new Map<string, PointsSummary>();
    for (const sheet of points.data?.sheets ?? []) {
      for (const row of sheet.students) {
        index.set(`${row.student_id}:${sheet.sheet_id}`, {
          earned: row.points_earned,
          possible: row.points_possible,
        });
      }
    }
    return index;
  }, [points.data]);

  const columns = useMemo(() => {
    const sheets = (points.data?.sheets ?? []).map((sheet) => ({
      id: sheet.sheet_id,
      label: sheet.sheet_title,
    }));
    return [...sheets, { id: TOTAL_COLUMN, label: t('totalColumn') }];
  }, [points.data, t]);

  const classTotal = useMemo(
    () => aggregatePoints([...byStudent.values()]),
    [byStudent],
  );
  const classRatio = pointsRatio(classTotal);

  const rows = useMemo(
    () =>
      (students.data ?? []).map((student) => ({
        id: student.id,
        // The points matrix names every pupil beside what they scored. In
        // projector mode the name becomes the UID — same row, same number,
        // no answer to "who is that". `studentNameParts` does the same for a
        // pupil whose record was anonymised and has no name to hide.
        ...(hideNames
          ? { firstName: student.uid, lastName: '' }
          : studentNameParts(student)),
      })),
    [students.data, hideNames],
  );

  const valueFor = (studentId: string, columnId: string): PointsValue | undefined =>
    columnId === TOTAL_COLUMN
      ? byStudent.get(studentId)
      : byCell.get(`${studentId}:${columnId}`);

  if (points.isLoading || students.isLoading) {
    return (
      <LoadingState
        shape="matrix"
        label={tc('loading')}
        rows={6}
        columns={5}
      />
    );
  }

  if (points.isError || students.isError) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={
          <Button
            onClick={() => {
              void points.refetch();
              void students.refetch();
            }}
          >
            {tc('retry')}
          </Button>
        }
      />
    );
  }

  const sheets = points.data?.sheets ?? [];

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-h1">{t('title')}</h1>
          {currentClass ? (
            <p className="text-body-s text-ink-500">
              {t('forClass', { code: currentClass.code })}
            </p>
          ) : null}
        </div>
        {/* Only rendered when projector mode is on. */}
        <RevealNames />
      </header>

      {/* Marks, narrowed to a part of the programme. On the canvas, not in a
          Card: two controls are not a separate object (DC-shape-01), and a
          full-width Card around them read as a section whose contents had gone
          missing. */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <CompetenceThemeFilter
          classId={classId}
          subjectId={subjectId ?? undefined}
          competencyId={competencyId}
          chapterId={chapterId}
          onCompetencyChange={setCompetency}
          onChapterChange={setChapter}
        />
      </div>

      {sheets.length === 0 ? (
        <EmptyState
          illustration={<IlloCurve />}
          title={t('empty.title')}
          description={t('empty.body')}
          action={
            <Link href="/sheets/new" className="no-underline">
              <Button>{t('empty.action')}</Button>
            </Link>
          }
        />
      ) : (
        <>
          <Card className="flex flex-wrap items-center gap-6">
            <ProgressRing
              value={classRatio ?? 0}
              centre={classRatio === null ? '—' : fmt.percent(classRatio)}
              label={t('classAverage')}
            />
            <div className="flex flex-col gap-1">
              <span className="text-label uppercase text-ink-500">{t('classAverage')}</span>
              {classTotal.earned === null ? (
                <span className="text-body-l text-ink-500">{t('notGradedYet')}</span>
              ) : (
                <span className="text-body-l font-bold text-ink-900" data-numeric>
                  {fmt.number(classTotal.earned, 2)} / {fmt.number(classTotal.possible, 2)}
                </span>
              )}
              <span className="text-body-s text-ink-500">
                {t('sheetCount', { count: sheets.length })}
              </span>
            </div>
          </Card>

          <Card flush className="p-4">
            <PointsMatrix
              students={rows}
              columns={columns}
              valueFor={valueFor}
              totalColumnId={TOTAL_COLUMN}
              caption={t('matrixCaption')}
              studentColumnLabel={t('studentColumn')}
              formatLabel={({ studentName, columnLabel, earned, possible, graded }) =>
                graded
                  ? t('cellLabel', {
                      student: studentName,
                      sheet: columnLabel,
                      earned: fmt.number(earned ?? 0, 2),
                      possible: fmt.number(possible, 2),
                    })
                  : t('cellLabelUngraded', { student: studentName, sheet: columnLabel })
              }
              renderStudentName={(student, name) => (
                <Link href={`/classes/${classId}/students/${student.id}`}>{name}</Link>
              )}
              // A cell is one pupil's copy of one sheet, so clicking it opens
              // exactly that: the breakdown, not the class-wide sheet. The
              // total column is a summary of several papers and opens nothing.
              onCellSelect={({ studentId, columnId }) => {
                if (columnId === TOTAL_COLUMN) return;
                router.push(
                  `/classes/${classId}/students/${studentId}/sheets/${columnId}`,
                );
              }}
            />
          </Card>

          <Card flush>
            <h2 className="p-4 pb-2 text-h3">{t('perSheet.title')}</h2>
            <ul className="m-0 flex list-none flex-col p-0">
              {sheets.map((sheet) => (
                <li key={sheet.sheet_id} className="border-t border-line">
                  <Link
                    href={`/sheets/${sheet.sheet_id}`}
                    className="flex min-h-14 flex-wrap items-center gap-3 p-4 no-underline"
                  >
                    <span className="min-w-0 flex-1 truncate text-body font-bold text-ink-900">
                      {sheet.sheet_title}
                    </span>
                    <span className="text-body-s text-ink-700" data-numeric>
                      {sheet.average_ratio === null
                        ? t('perSheet.notGraded')
                        : fmt.percent(sheet.average_ratio)}
                    </span>
                    <IconChevronRight size={18} className="text-ink-500" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
