'use client';

import {
  AiBadge,
  Badge,
  Button,
  ConfidenceBar,
  Field,
  IconEdit,
  IconButton,
  Panel,
  SegmentedControl,
  Textarea,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import type { DetectionCorrection, DetectionOut } from '@/lib/api/types';
import { badgeVariant } from '@/lib/detectionOutcome';

type Verdict = 'correct' | 'wrong' | 'unsure';

function verdictOf(d: DetectionOut): Verdict {
  if (d.verdict_correct === true) return 'correct';
  if (d.verdict_correct === false) return 'wrong';
  return 'unsure';
}

export interface OpenAnswerCardProps {
  detection: DetectionOut;
  selected: boolean;
  readOnly: boolean;
  /** Below this the pipeline stops trusting itself; from `@alppy/shared`. */
  lowConfidence: number;
  onSelect: () => void;
  onCorrect: (body: DetectionCorrection) => void;
}

/**
 * One written answer under review: the box as it was cut from the page, what
 * the model read in it, its verdict against the expected answer, and one
 * control to overrule it.
 *
 * The transcription is set in the mono face because it is data the teacher
 * audits, not prose; the verdict carries the AI badge because a model wrote
 * it — the one thing the mandarin accent means. Accepting is doing nothing:
 * the verdict stands as read until the teacher says otherwise, and nothing
 * reaches the mastery model before they confirm the pile.
 */
export function OpenAnswerCard({
  detection,
  selected,
  readOnly,
  lowConfidence,
  onSelect,
  onCorrect,
}: OpenAnswerCardProps) {
  const t = useTranslations('scans');
  const to = useTranslations('scans.openAnswer');
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(detection.transcription ?? '');

  const pending = detection.outcome === 'pending';
  const blank = detection.outcome === 'blank';
  const hasVerdict = detection.verdict_correct !== null;
  const machineRead = detection.machine_transcription !== null || detection.machine_verdict_correct !== null;
  const verdictWord = (value: boolean | null) =>
    value === true ? to('verdictCorrect') : value === false ? to('verdictWrong') : to('verdictNone');

  return (
    <Panel
      sunken={detection.outcome === 'low_confidence' || detection.outcome === 'not_gradeable'}
      onClick={onSelect}
      className={selected ? 'shadow-[var(--focus-ring)]' : undefined}
      data-open-answer=""
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="mono text-body-s" data-numeric>
          #{detection.number ?? detection.item_index + 1}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          {detection.ai_generated ? <AiBadge label={t('aiGenerated')} size="sm" /> : null}
          {machineRead ? <AiBadge label={to('readByAi')} size="sm" /> : null}
          <Badge variant={badgeVariant(detection.outcome)}>
            {t(`outcome.${detection.outcome}`)}
          </Badge>
        </div>
      </div>

      {detection.statement ? (
        <p className="mt-2 text-body-s text-ink-900">{detection.statement}</p>
      ) : null}

      {/* The box, as cut from the registered page with Alppy's ink removed. */}
      {detection.crop_url ? (
        <figure className="mt-3">
          <figcaption className="text-label uppercase text-ink-700">{to('crop')}</figcaption>
          <img
            src={detection.crop_url}
            alt={to('cropAlt', { number: detection.number ?? detection.item_index + 1 })}
            className="mt-1 block w-full rounded-sm border border-line bg-surface"
          />
        </figure>
      ) : null}

      {pending ? (
        <p className="mt-2 text-body-s text-ink-700" role="status">
          {to('pendingHelp')}
        </p>
      ) : null}
      {blank ? <p className="mt-2 text-body-s text-ink-700">{to('blankHelp')}</p> : null}

      {!pending && !blank ? (
        <div className="mt-3 flex flex-col gap-3">
          {/* What was read: data, so it is set as data. */}
          <div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-label uppercase text-ink-700">{to('transcription')}</span>
              {!readOnly ? (
                <IconButton
                  label={to('editTranscription')}
                  icon={<IconEdit />}
                  variant="ghost"
                  size="sm"
                  onClick={(event) => {
                    event.stopPropagation();
                    setEditing((current) => !current);
                  }}
                />
              ) : null}
            </div>
            {editing ? (
              <Field label={to('editTranscription')} hideLabel>
                <div className="flex flex-col gap-2">
                  <Textarea
                    value={draft}
                    rows={2}
                    className="mono"
                    onChange={(event) => setDraft(event.currentTarget.value)}
                  />
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      onClick={(event) => {
                        event.stopPropagation();
                        onCorrect({ transcription: draft });
                        setEditing(false);
                      }}
                    >
                      {t('confirmTranscription')}
                    </Button>
                  </div>
                </div>
              </Field>
            ) : (
              <p className="mono mt-1 rounded-sm border border-line bg-surface-2 px-3 py-2 text-body-s">
                {detection.transcription ?? '—'}
              </p>
            )}
          </div>

          <p className="text-body-s text-ink-700">
            {detection.answer_text ? (
              <>
                {to('expected', { answer: '' })}
                <span className="mono">{detection.answer_text}</span>
              </>
            ) : (
              to('noExpected')
            )}
          </p>

          {hasVerdict || detection.outcome === 'corrected' ? (
            <ConfidenceBar
              value={detection.confidence}
              threshold={lowConfidence}
              label={t('confidence')}
              lowLabel={t('lowConfidence')}
            />
          ) : (
            <p className="text-body-s text-warn-600">{to('ungradeableHelp')}</p>
          )}

          {/* The machine's reading is kept beside the override, not under it. */}
          {detection.corrected_at && machineRead ? (
            <p className="text-body-s text-ink-500">
              {to('machineVerdict', {
                verdict: verdictWord(detection.machine_verdict_correct),
                transcription: detection.machine_transcription ?? '—',
              })}
            </p>
          ) : null}

          {!readOnly ? (
            <SegmentedControl<Verdict>
              value={verdictOf(detection)}
              onValueChange={(value) =>
                onCorrect({
                  verdict_correct: value === 'correct' ? true : value === 'wrong' ? false : null,
                })
              }
              label={to('verdict')}
              block
              options={[
                { value: 'correct', label: to('correct') },
                { value: 'wrong', label: to('wrong') },
                { value: 'unsure', label: to('unsure') },
              ]}
            />
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}
