'use client';

import {
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  IlloCurve,
  LoadingState,
  MasteryMatrix,
  Panel,
  type MasteryBand,
  type MasteryValue,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { use, useMemo } from 'react';

import { Link, useRouter } from '@/i18n/navigation';
import { useClass, useClassMastery, useStudents } from '@/lib/api/queries';
import { useBandLabels, BAND_KEYS } from '@/lib/bands';

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
  const router = useRouter();

  const klass = useClass(classId);
  const students = useStudents(classId);
  const mastery = useClassMastery(classId);

  // The matrix asks for a value per (student, competency); an index keeps that
  // lookup O(1) rather than scanning the cell list for every cell drawn.
  const cellIndex = useMemo(() => {
    const map = new Map<string, MasteryValue>();
    for (const cell of mastery.data?.cells ?? []) {
      map.set(`${cell.student_id}:${cell.competency_id}`, {
        band: cell.band as MasteryBand,
        score: cell.score,
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
          action={<Button variant="primary">{t('empty.action')}</Button>}
        />
      ) : competencies.length === 0 ? (
        <EmptyState
          illustration={<IlloCurve />}
          title={tm('empty.title')}
          description={tm('empty.body')}
          action={
            <Link href="/sheets/new">
              <Button variant="primary">{tm('empty.action')}</Button>
            </Link>
          }
        />
      ) : (
        <>
          {/* The legend is not decoration: colour is never the only channel, so
              the words have to be on the page next to the grid. */}
          <Panel className="mb-4">
            <h2 className="mb-2 text-label text-ink-500">{tm('legend')}</h2>
            <ul className="flex list-none flex-wrap gap-2 p-0">
              {BAND_KEYS.map((band) => (
                <li key={band}>
                  <Chip>{bandLabels[band]}</Chip>
                </li>
              ))}
            </ul>
          </Panel>

          <Card flush>
            <MasteryMatrix
              students={roster.map((s) => ({
                id: s.id,
                firstName: s.first_name,
                lastName: s.last_name,
                uid: s.uid,
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
              caption={t('matrix')}
              studentColumnLabel={t('roster')}
              onCellSelect={({ studentId }) =>
                router.push(`/classes/${classId}/students/${studentId}`)
              }
              bleed
            />
          </Card>
        </>
      )}
    </div>
  );
}
