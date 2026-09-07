'use client';

import { AiBadge, Badge, Button, Panel } from '@alppy/ui';
import { useTranslations } from 'next-intl';

import type { MisconceptionNoteOut, Uuid } from '@/lib/api/types';

export interface FeedbackNoteCardProps {
  note: MisconceptionNoteOut;
  busy?: boolean;
  onApprove: (feedbackId: Uuid) => void;
  onDiscard: (feedbackId: Uuid) => void;
}

/**
 * One student's misconception note, as the teacher must read it before it is
 * printed and handed to that student.
 *
 * The note is shown in full, never summarised behind a count. Approving text
 * you have not read is the failure this screen exists to prevent, and it
 * matters more here than for a generated exercise: a wrong exercise is a bad
 * question, a wrong note is a claim about how a named child thinks.
 *
 * There is no edit affordance. A teacher who disagrees with a note discards it
 * — rewriting a machine's account of a child's thinking in the machine's voice
 * would leave the accent claiming authorship of a sentence the teacher wrote,
 * which is the one thing that mark may never do (DESIGN.md §1).
 */
export function FeedbackNoteCard({
  note,
  busy = false,
  onApprove,
  onDiscard,
}: FeedbackNoteCardProps) {
  const t = useTranslations('adaptive');
  const approved = note.approved_at != null;

  return (
    <Panel className="bg-surface" data-ai-item="">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-display text-h3 font-bold">{note.student_uid}</span>
        <AiBadge label={t('aiBadge')} size="sm" />
        <span className="flex-1" />
        {approved ? <Badge variant="success">{t('feedbackApproved')}</Badge> : null}
      </div>

      {/* Student-facing prose, so it is set at the floor the printed page uses. */}
      <ol className="m-0 flex list-none flex-col gap-2 p-0">
        {note.notes.map((line, index) => (
          <li key={index} className="flex gap-3 text-body-l">
            <span className="font-display font-bold tabular-nums text-ink-500">{index + 1}</span>
            <span>{line}</span>
          </li>
        ))}
      </ol>

      {approved ? null : (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" size="sm" disabled={busy} onClick={() => onApprove(note.id)}>
            {t('approveOne')}
          </Button>
          <Button size="sm" disabled={busy} onClick={() => onDiscard(note.id)}>
            {t('feedbackDiscard')}
          </Button>
        </div>
      )}
    </Panel>
  );
}
