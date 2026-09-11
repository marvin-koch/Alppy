'use client';

import {
  AttemptList,
  Button,
  ConceptTag,
  ErrorState,
  LoadingState,
  MasteryMeter,
  Sheet,
  type MasteryBand,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';

import { Link } from '@/i18n/navigation';
import { useCompetencyAttempts } from '@/lib/api/queries';
import type { Uuid } from '@/lib/api/types';
import { useBandLabels } from '@/lib/bands';
import { useDiscretion } from '@/lib/discreet';
import { pupilLabel } from '@/lib/pupil-label';
import { useFormatters } from '@/lib/format';

export interface CellDrillDownProps {
  studentId: Uuid;
  competencyId: Uuid;
  onClose: () => void;
  onOpenProfile: () => void;
}

/**
 * The evidence behind one matrix cell.
 *
 * A band is an argument the teacher is entitled to check, so this shows every
 * attempt that produced it, each linking back to the sheet it was printed on
 * and the scan it was read from. Clicking a cell used to land on the student
 * profile with the competency thrown away and no attempts anywhere in the
 * product.
 */
export function CellDrillDown({
  studentId,
  competencyId,
  onClose,
  onOpenProfile,
}: CellDrillDownProps) {
  const t = useTranslations('attempts');
  const tm = useTranslations('mastery');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const locale = useLocale();
  const fmt = useFormatters();
  const bandLabels = useBandLabels();
  // This panel is one click from the matrix and was the last identity-hiding
  // path that did not ask: it rendered the pupil's full name as its title while
  // the grid behind it was showing UIDs, so projector mode leaked exactly where
  // a teacher is most likely to click during a lesson (DC-content, D94).
  const { hideNames } = useDiscretion();

  const { data, isLoading, isError, refetch } = useCompetencyAttempts(studentId, competencyId);

  const competencyLabel =
    data?.competency.labels?.[locale] ?? data?.competency.labels?.fr ?? data?.competency.code ?? '';

  return (
    <Sheet
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      side="right"
      closeLabel={tc('close')}
      title={data ? pupilLabel(data.student, hideNames) : t('title')}
      description={data ? `${data.competency.code} · ${competencyLabel}` : undefined}
      footer={
        <Button variant="primary" onClick={onOpenProfile}>
          {t('openProfile')}
        </Button>
      }
    >
      {isLoading ? <LoadingState shape="list" label={tc('loading')} /> : null}

      {isError ? (
        <ErrorState
          title={te('title')}
          description={te('body')}
          action={<Button onClick={() => void refetch()}>{tc('retry')}</Button>}
        />
      ) : null}

      {data ? (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <ConceptTag code={data.competency.code} />
            {data.provisional ? (
              <span className="ard-chip text-label">{tm('provisional')}</span>
            ) : null}
            <MasteryMeter
              band={data.band as MasteryBand}
              score={data.band === 'none' ? null : data.score}
              bandLabel={bandLabels[data.band as MasteryBand]}
              caption={
                data.provisional
                  ? tm('provisionalHelp')
                  : data.days_until_review === null
                    ? undefined
                    : data.days_until_review === 0
                      ? tm('reviewOverdue')
                      : tm('reviewDue', { days: data.days_until_review })
              }
            />
          </div>

          <AttemptList
            attempts={data.attempts.map((attempt) => ({
              id: attempt.id,
              statement: attempt.statement,
              correct: attempt.correct,
              difficulty: attempt.difficulty,
              answeredAt: fmt.dateTime(attempt.answered_at),
              generated: attempt.origin === 'ai_generated',
              corrected: attempt.corrected,
            }))}
            labels={{
              correct: t('correct'),
              incorrect: t('incorrect'),
              corrected: t('corrected'),
              difficulty: t('difficulty'),
              aiBadge: tm('aiBadge'),
              empty: t('empty'),
            }}
            renderProvenance={(row) => {
              const source = data.attempts.find((a) => a.id === row.id);
              if (!source) return null;
              return (
                <>
                  {source.sheet_id ? (
                    <Link href={`/sheets/${source.sheet_id}`}>
                      {t('fromSheet', { title: source.sheet_title ?? '' })}
                    </Link>
                  ) : null}
                  {source.scan_id ? (
                    <Link href={`/scans/${source.scan_id}`}>{t('fromScan')}</Link>
                  ) : null}
                </>
              );
            }}
          />
        </div>
      ) : null}
    </Sheet>
  );
}
