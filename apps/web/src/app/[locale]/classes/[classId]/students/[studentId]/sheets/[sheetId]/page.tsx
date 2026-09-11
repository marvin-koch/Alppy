'use client';

import {
  AiBadge,
  Badge,
  Breadcrumb,
  Button,
  Card,
  EmptyState,
  ErrorState,
  IconChevronRight,
  IlloTray,
  LoadingState,
  Panel,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { use } from 'react';

import { Link } from '@/i18n/navigation';
import { useStudentSheet } from '@/lib/api/queries';
import type { StudentSheetItemOut, Uuid } from '@/lib/api/types';
import { useFormatters } from '@/lib/format';
import { pointsRatio } from '@/lib/points';
import { useDiscretion } from '@/lib/discreet';

/**
 * One pupil's copy, question by question.
 *
 * The end of the tracking drill-down — Suivi → pupil → this sheet — and the view
 * a teacher has open while handing the paper back. Three things per question,
 * because those are the three a pupil asks about: what I put, what was wanted,
 * and what it cost me.
 *
 * The distinction the whole screen turns on: an item with no attempt is *not*
 * an item scored zero. It shows a dash and the word "not graded", never 0 pts.
 */
export default function StudentSheetPage({
  params,
}: {
  params: Promise<{ classId: Uuid; studentId: Uuid; sheetId: Uuid }>;
}) {
  const { classId, studentId, sheetId } = use(params);
  const t = useTranslations('studentSheet');
  const { hideNames } = useDiscretion();
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const a11y = useTranslations('a11y');
  const fmt = useFormatters();
  const { data, isLoading, isError, refetch } = useStudentSheet(studentId, sheetId);

  if (isLoading) return <LoadingState shape="list" label={tc('loading')} rows={6} />;
  if (isError || !data) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={<Button onClick={() => void refetch()}>{tc('retry')}</Button>}
      />
    );
  }

  // Even here, where the teacher arrived by choosing this pupil: the screen
  // can still be projected, and the point of the mode is that it holds
  // everywhere rather than on the screens someone remembered.
  const name = hideNames
    ? data.student.uid
    : `${data.student.first_name} ${data.student.last_name}`.trim();
  const ratio = pointsRatio({ earned: data.points_earned, possible: data.points_possible });

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <header className="flex flex-col gap-1">
        <Breadcrumb
          label={a11y('breadcrumb')}
          items={[
            {
              label: t('back'),
              href: `/classes/${classId}/students/${studentId}`,
              key: 'student',
            },
            { label: data.sheet_title, key: 'sheet' },
          ]}
          renderLink={(item, children) => <Link href={item.href!}>{children}</Link>}
        />
        <h1 className="text-h1">{data.sheet_title}</h1>
        <p className="text-body-s text-ink-500">{t('title', { student: name })}</p>
      </header>

      {/* The total, stated once and clearly — it is the number the pupil asks
          about first. */}
      <Card className="flex flex-wrap items-baseline justify-between gap-3">
        <span className="text-label uppercase text-ink-500">{t('total')}</span>
        {data.points_earned === null ? (
          <span className="text-h2 text-ink-500">{t('notGradedYet')}</span>
        ) : (
          <span className="text-h2 font-bold text-ink-900" data-numeric>
            {fmt.number(data.points_earned, 2)} / {fmt.number(data.points_possible, 2)}
            {ratio === null ? null : (
              <span className="ml-3 text-body-l text-ink-500">{fmt.percent(ratio)}</span>
            )}
          </span>
        )}
        {data.scan_id ? (
          <Link
            href={`/scans/${data.scan_id}`}
            className="flex min-h-11 items-center gap-1 text-body-s"
          >
            {t('openScan')}
            <IconChevronRight size={16} aria-hidden />
          </Link>
        ) : null}
      </Card>

      {data.items.length === 0 ? (
        <EmptyState
          illustration={<IlloTray />}
          title={t('empty.title')}
          description={t('empty.body')}
          size="sm"
        />
      ) : (
        <ol className="m-0 flex list-none flex-col gap-3 p-0">
          {data.items.map((item) => (
            <li key={item.exercise_id}>
              <ItemCard item={item} />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** One question: the statement, the two answers side by side, and the mark. */
function ItemCard({ item }: { item: StudentSheetItemOut }) {
  const t = useTranslations('studentSheet');
  const ts = useTranslations('scans');
  const fmt = useFormatters();

  // Three states, never two: graded-right, graded-wrong, and not graded at all.
  // The third is the one that must not be allowed to look like a zero.
  const verdict =
    item.correct === null
      ? { label: t('ungraded'), variant: 'neutral' as const }
      : item.correct
        ? { label: t('correct'), variant: 'success' as const }
        : { label: t('incorrect'), variant: 'danger' as const };

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="min-w-0 flex-1 text-body" data-student-facing>
          <span className="mr-2 font-mono font-bold text-ink-500" data-numeric>
            {item.number ?? item.position + 1}.
          </span>
          {item.statement}
        </p>
        <div className="flex shrink-0 items-center gap-2">
          {item.ai_generated ? <AiBadge label={ts('aiGenerated')} size="sm" /> : null}
          {/* Colour AND a word, always. */}
          <Badge variant={verdict.variant}>{verdict.label}</Badge>
          <span className="text-body-s font-bold text-ink-900" data-numeric>
            {item.points_earned === null
              ? t('pointsUngraded', { possible: fmt.number(item.points_possible, 2) })
              : t('points', {
                  // Both through `fmt`, both `fr-CH`. `possible` used to be an
                  // ICU `{possible, number}`, formatted by next-intl with `fr`
                  // — so this one line could read `3.25 / 4,5 pts`.
                  earned: fmt.number(item.points_earned, 2),
                  possible: fmt.number(item.points_possible, 2),
                })}
          </span>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <Panel sunken className="flex flex-col gap-1">
          <span className="text-label uppercase text-ink-500">{t('given')}</span>
          <span className={item.given ? 'text-body text-ink-900' : 'text-body text-ink-500'}>
            {item.given ?? t('noAnswer')}
          </span>
        </Panel>
        <Panel sunken className="flex flex-col gap-1">
          <span className="text-label uppercase text-ink-500">{t('expected')}</span>
          <span className={item.expected ? 'text-body text-ink-900' : 'text-body text-ink-500'}>
            {item.expected ?? t('noExpected')}
          </span>
        </Panel>
      </div>

      {/* The crop of what they actually wrote, when there is one — the answer
          rendered on the site rather than only inside the PDF. */}
      {item.crop_url ? (
        <img
          src={item.crop_url}
          alt={t('given')}
          className="max-h-40 w-full rounded-md border border-line object-contain"
        />
      ) : null}
    </Card>
  );
}
