'use client';

import {
  Breadcrumb,
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  IconChevronRight,
  IlloCompass,
  LoadingState,
  MasteryBandTag,
  type MasteryBand,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { use, useMemo } from 'react';

import { Link } from '@/i18n/navigation';
import { useBandLabels } from '@/lib/bands';
import * as api from '@/lib/api/endpoints';
import { useClass, useClassMastery } from '@/lib/api/queries';
import type { MasteryCell, Uuid } from '@/lib/api/types';
import { ExportButton } from '@/components/ExportButton';
import { RevealNames } from '@/components/RevealNames';
import { useDiscretion } from '@/lib/discreet';
import { studentSortName } from '@/lib/studentName';
import { requestIdOf } from '@/lib/api/error-message';

/**
 * Worst first, and `none` is not a weakness — it is the absence of evidence.
 * The same reading `tree_service._weakest` and `_weakest_first` take one level
 * down, so the roster and the matrix cannot disagree about who needs looking at.
 */
const SEVERITY: Record<MasteryBand, number> = {
  fading: 0,
  weak: 1,
  ok: 2,
  solid: 3,
  none: 4,
};

interface RosterRow {
  id: Uuid;
  number: number;
  name: string;
  uid: string;
  /** The worst band this pupil has been ASSESSED on, or null if none yet. */
  weakest: MasteryBand | null;
  /** Home first, then anywhere else they sit. Two entries means a visitor. */
  classCodes: string[];
  homeClassCode: string;
  /** How many assessed competencies are weak or fading — the number that varies. */
  attention: number;
  assessed: number;
  total: number;
}

/** `mastery_service.ATTENTION_BANDS`, the same two the home screen counts. */
const ATTENTION: ReadonlySet<MasteryBand> = new Set<MasteryBand>(['weak', 'fading']);

export default function StudentsPage({ params }: { params: Promise<{ classId: string }> }) {
  const { classId } = use(params);
  const t = useTranslations('students');
  const { hideNames } = useDiscretion();
  const tc = useTranslations('classes');
  const tcode = useTranslations('errors.code');
  const tcommon = useTranslations('common');
  const te = useTranslations('errors.generic');
  const a11y = useTranslations('a11y');
  const bandLabels = useBandLabels();

  const klass = useClass(classId as Uuid);
  // The matrix already carries the roster (`MasteryMatrixOut.students`), so
  // asking `/classes/{id}/students` as well fetched every child's name a
  // second time to render the same list. Reading it from the one response
  // also fixes the flash this had: the roster used to arrive first and the
  // page rendered every pupil at "0 assessed" until the matrix caught up.
  const matrix = useClassMastery(classId as Uuid, {});
  const students = matrix.data?.students;

  const rows: RosterRow[] = useMemo(() => {
    const cells = matrix.data?.cells ?? [];
    const byStudent = new Map<string, MasteryCell[]>();
    for (const cell of cells) {
      const list = byStudent.get(cell.student_id) ?? [];
      list.push(cell);
      byStudent.set(cell.student_id, list);
    }
    const total = matrix.data?.competencies.length ?? 0;

    return (students ?? []).map((s) => {
      const mine = byStudent.get(s.id) ?? [];
      // Deliberately NOT a mean of the cells. A client-side average would be a
      // second scoring rule sitting beside `roll_up_mastery`, and D58 rejected
      // exactly that: what a roster is for is triage — who to look at first —
      // not a mastery claim about the child.
      const assessed = mine.filter((c) => c.band !== 'none');
      const weakest = assessed.length
        ? assessed.reduce((worst, c) => (SEVERITY[c.band] < SEVERITY[worst.band] ? c : worst)).band
        : null;
      return {
        id: s.id,
        attention: assessed.filter((c) => ATTENTION.has(c.band)).length,
        classCodes: s.class_codes,
        homeClassCode: s.home_class_code,
        number: s.number,
        // Projector mode replaces the name with the code already printed on
        // that pupil's own paper: the teacher can still resolve it, the room
        // cannot. `studentSortName` falls back to the same code for a pupil
        // who HAS no name, because their record was anonymised.
        name: hideNames ? s.uid : studentSortName(s),
        uid: s.uid,
        weakest,
        assessed: assessed.length,
        total,
      };
    });
    // `hideNames` belongs here: without it the rows keep the labels they
    // were memoised with, and toggling projector mode changes nothing on
    // screen until something else happens to invalidate them.
  }, [students, matrix.data, hideNames]);

  const crumbs = [
    { label: klass.data?.code ?? '', href: `/classes/${classId}`, key: 'class' },
    { label: t('title'), key: 'students' },
  ];

  const header = (
    <>
      <Breadcrumb
        className="mb-2"
        label={a11y('breadcrumb')}
        items={crumbs}
        renderLink={(item, children) => <Link href={item.href!}>{children}</Link>}
      />
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1>{t('heading', { code: klass.data?.code ?? '' })}</h1>
          <p className="text-body-s text-ink-500">{t('count', { count: rows.length })}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <RevealNames />
          {/* The class export (D36). `privacy.md` §4 has promised it since it
              was written, the route has existed since the last pass, and
              nothing in the product could reach either — so a school taking its
              data elsewhere ended at "ask whoever runs the server". */}
          <ExportButton
            fetcher={() => api.exportClass(classId as Uuid)}
            subject={klass.data?.code ?? 'class'}
            label={t('export')}
            busyLabel={tcommon('loading')}
            translateError={tcode}
          />
          <Link href={`/classes/${classId}/roster`}>
            <Button variant="primary">{tc('addStudents')}</Button>
          </Link>
        </div>
      </header>
    </>
  );

  if (matrix.isLoading) {
    return (
      <div className="mx-auto max-w-4xl">
        {header}
        <LoadingState shape="list" rows={6} label={a11y('loading')} />
      </div>
    );
  }

  if (matrix.isError) {
    return (
      <div className="mx-auto max-w-4xl">
        {header}
        <ErrorState
          title={te('title')}
          description={te('body')}
          requestId={requestIdOf(matrix.error)}
          action={
            <Button variant="secondary" onClick={() => void matrix.refetch()}>
              {te('action')}
            </Button>
          }
        />
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="mx-auto max-w-4xl">
        {header}
        <EmptyState
          illustration={<IlloCompass />}
          title={t('empty.title')}
          description={t('empty.body')}
          action={
            <Link href={`/classes/${classId}/roster`}>
              <Button variant="primary">{tc('addStudents')}</Button>
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl">
      {header}
      <Card flush>
        <ul className="divide-y divide-line">
          {rows.map((row) => (
            <li key={row.id}>
              <Link
                href={`/classes/${classId}/students/${row.id}`}
                className="flex min-h-[44px] flex-wrap items-center gap-3 px-4 py-3 no-underline hover:bg-surface-2"
              >
                <span className="w-6 shrink-0 text-body-s text-ink-500" data-numeric>
                  {row.number}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-bold text-ink-900">{row.name}</span>
                  <span className="flex flex-wrap items-center gap-2">
                    {/* The uid is data a person reads off paper, so it is mono
                        like every other transcribed value (DC-type-04). */}
                    <span className="font-mono text-body-s text-ink-500">{row.uid}</span>
                    {/* Only a VISITOR gets chips. Printing "7B" on every row of
                        the 7B roster is furniture; the whole signal is that one
                        pupil's identifier came from somewhere else. */}
                    {row.classCodes.length > 1
                      ? row.classCodes.map((code) => (
                          <Chip
                            key={code}
                            variant={code === row.homeClassCode ? 'primary' : 'neutral'}
                          >
                            {code === row.homeClassCode ? t('homeClass', { code }) : code}
                          </Chip>
                        ))
                      : null}
                  </span>
                </span>
                {row.weakest === null ? (
                  <MasteryBandTag band="none" label={bandLabels.none} />
                ) : (
                  <MasteryBandTag
                    band={row.weakest}
                    label={bandLabels[row.weakest]}
                    // A band on a roster row is a "look here first", so it says
                    // what it is made of: green over one assessed competency and
                    // green over eleven look identical otherwise (DC-content-07).
                    // The band alone saturates: the weakest of seven
                    // competencies is nearly always the worst one, so a roster
                    // of eighteen reads "S'efface" eighteen times — the
                    // constant-not-a-signal failure D58 rejected for roll-ups.
                    // The count is what actually separates one pupil from the
                    // next, and it is the number the home screen already
                    // counts (`students_needing_attention`).
                    caption={
                      row.attention > 0
                        ? t('attention', {
                            count: row.attention,
                            assessed: row.assessed,
                          })
                        : row.assessed < row.total
                          ? t('assessed', { assessed: row.assessed, total: row.total })
                          : undefined
                    }
                  />
                )}
                <IconChevronRight size={16} className="text-ink-300" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
      <p className="mt-3 px-1 text-body-s text-ink-500">{t('weakestNote')}</p>
    </div>
  );
}
