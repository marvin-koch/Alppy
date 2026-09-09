'use client';

import { Badge, Checkbox, Panel } from '@alppy/ui';
import { useTranslations } from 'next-intl';
import type { ReactNode } from 'react';

import type { ExerciseOut, ExerciseType } from '@/lib/api/types';
import { optionLetters } from '@/lib/optionLetters';

/**
 * Which badge colour each exercise type wears.
 *
 * One definition, because "never colour alone" (DESIGN.md §1) only holds if the
 * colour and the label agree everywhere — three copies of this map means a
 * fourth type, or a change of colour, lands in two of the three places.
 */
export const TYPE_VARIANT: Record<ExerciseType, 'info' | 'success' | 'warn'> = {
  mcq: 'info',
  true_false: 'success',
  open: 'warn',
};

interface Props {
  exercise: ExerciseOut;
  checked: boolean;
  disabled?: boolean;
  onToggle: () => void;
  /** Extra badges beside the type and difficulty — the AI accent, a page. */
  badges?: ReactNode;
  /** Rendered under the row: provenance, a caveat. */
  footer?: ReactNode;
}

/**
 * One tickable exercise, wherever the teacher is choosing from.
 *
 * Shared by the document picker and the retrieval tab on purpose: a checkbox
 * means the same thing on both — "this is on the sheet" — and so the two must
 * not drift into looking or behaving differently. It is also the single place
 * that guarantees a printed statement renders at `body-l`.
 */
export function ExerciseRow({
  exercise,
  checked,
  disabled = false,
  onToggle,
  badges,
  footer,
}: Props) {
  const tx = useTranslations('exercise');
  const letters = optionLetters(exercise.type, exercise.language);

  return (
    <Panel className={checked ? 'border-primary-200 bg-primary-050' : undefined}>
      <Checkbox
        checked={checked}
        disabled={disabled}
        onChange={onToggle}
        label={
          <span className="flex flex-col gap-1.5">
            <span className="flex flex-wrap items-center gap-2">
              <Badge variant={TYPE_VARIANT[exercise.type]}>{tx(`type.${exercise.type}`)}</Badge>
              <Badge variant="neutral">
                {tx('difficultyLevel', { level: exercise.difficulty })}
              </Badge>
              {badges}
            </span>
            {exercise.label ? (
              <span className="flex flex-wrap items-baseline gap-x-2 font-semibold">
                <span className="mono text-ink-700">{exercise.label}</span>
                {exercise.title ? <span>{exercise.title}</span> : null}
              </span>
            ) : null}
            {exercise.figure_url ? (
              /* The picture IS what the sheet prints: the figure, the table,
                 the fractions, in the book's own setting. The wording stays as
                 the alt, so the row still reads without images. */
              <img
                src={exercise.figure_url}
                alt={tx('figureAlt', { label: exercise.label ?? '' })}
                title={exercise.statement}
                loading="lazy"
                className="block max-w-full rounded-md border border-line bg-surface"
                style={{ maxHeight: '18rem', width: 'auto' }}
              />
            ) : (
              /* Student-facing: this is the wording that will be printed, and it
                 never drops below body-l. */
              <span data-student-facing>{exercise.statement}</span>
            )}
            {exercise.options ? (
              <span className="flex flex-wrap gap-x-5 gap-y-1 text-body-s text-ink-700">
                {exercise.options.map((option, index) => (
                  <span key={index}>
                    {/* The glyph the sheet actually prints: ABCD for a choice,
                        V/F, R/F or T/F by the exercise's own language. */}
                    <span className="mono mr-1 text-ink-500">{letters[index] ?? ''}</span>
                    {option}
                  </span>
                ))}
              </span>
            ) : null}
          </span>
        }
      />
      {footer}
    </Panel>
  );
}
