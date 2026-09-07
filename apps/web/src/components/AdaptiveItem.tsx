'use client';

import { AiBadge, Button, IconAi, IconEdit, IconTrash, Panel, Textarea } from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import type { ExerciseProposal, Uuid } from '@/lib/api/types';

export interface AdaptiveItemProps {
  proposal: ExerciseProposal;
  /** 1-based position on the sheet, as the student will read it. */
  number: number;
  /** Group mode only: which students this shared item is actually for. */
  forStudentUids?: string[];
  busy?: boolean;
  onEdit: (exerciseId: Uuid, statement: string) => void;
  onRegenerate: (exerciseId: Uuid) => void;
  onDiscard: (exerciseId: Uuid) => void;
}

/**
 * One proposed exercise, as the teacher has to read it before approving it.
 *
 * The whole point of the approval step is that a person looked at the item. A
 * badge and a count are not that: they let a teacher approve nine exercises
 * they have never seen. So the statement, the options and the marked answer are
 * all on screen, and the AI ones carry the mandarin mark plus the word.
 *
 * Edit / regenerate / discard are offered only for generated items. A textbook
 * exercise belongs to the teacher's own material and is not ours to rewrite.
 */
export function AdaptiveItem({
  proposal,
  number,
  forStudentUids,
  busy = false,
  onEdit,
  onRegenerate,
  onDiscard,
}: AdaptiveItemProps) {
  const t = useTranslations('adaptive');
  const { exercise, provenance } = proposal;
  const isAi = exercise.origin === 'ai_generated';

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(exercise.statement);

  const answer =
    exercise.type === 'true_false'
      ? exercise.answer_bool
        ? t('trueLabel')
        : t('falseLabel')
      : exercise.answer_index != null
        ? (exercise.options?.[exercise.answer_index] ?? null)
        : null;

  return (
    <li className="list-none">
      <Panel data-ai-item={isAi ? '' : undefined} data-testid="adaptive-item">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <span className="text-label text-ink-500" data-numeric>
            {number}
          </span>
          {isAi ? <AiBadge label={t('aiBadge')} size="sm" /> : null}
        </div>

        {editing ? (
          <div className="mt-2">
            <Textarea
              aria-label={t('statement')}
              value={draft}
              rows={3}
              onChange={(event) => setDraft(event.target.value)}
            />
            <div className="mt-2 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="primary"
                disabled={busy || draft.trim().length < 8}
                onClick={() => {
                  onEdit(exercise.id, draft.trim());
                  setEditing(false);
                }}
              >
                {t('save')}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setDraft(exercise.statement);
                  setEditing(false);
                }}
              >
                {t('cancel')}
              </Button>
            </div>
          </div>
        ) : (
          <p className="mt-1 text-body">{exercise.statement}</p>
        )}

        {exercise.options?.length ? (
          <ol className="mt-2 flex list-none flex-col gap-1 p-0 text-body-s">
            {exercise.options.map((option, index) => (
              <li key={`${option}-${index}`} className="flex gap-2">
                <span className="mono text-ink-500">{String.fromCharCode(65 + index)}</span>
                <span className={index === exercise.answer_index ? 'font-bold' : undefined}>
                  {option}
                </span>
              </li>
            ))}
          </ol>
        ) : null}

        <p className="mt-2 text-body-s text-ink-500">
          {answer ? `${t('correctAnswer')} · ${answer} · ` : null}
          {t('difficulty', { level: exercise.difficulty })}
        </p>

        {provenance.reason ? (
          <p className="mt-1 text-body-s text-ink-500">{provenance.reason}</p>
        ) : null}

        {forStudentUids?.length ? (
          <p className="mt-1 text-body-s text-ink-500" data-numeric>
            {t('forStudents', { uids: forStudentUids.join(', ') })}
          </p>
        ) : null}

        {isAi && !editing ? (
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              leadingIcon={<IconEdit />}
              disabled={busy}
              onClick={() => setEditing(true)}
            >
              {t('edit')}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              leadingIcon={<IconAi />}
              loading={busy}
              busyLabel={t('regenerating')}
              onClick={() => onRegenerate(exercise.id)}
            >
              {t('regenerate')}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              leadingIcon={<IconTrash />}
              disabled={busy}
              onClick={() => onDiscard(exercise.id)}
            >
              {t('discard')}
            </Button>
          </div>
        ) : null}
      </Panel>
    </li>
  );
}
