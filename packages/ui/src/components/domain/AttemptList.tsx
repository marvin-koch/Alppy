import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { AiBadge } from './AiBadge';

export interface AttemptRow {
  id: string;
  /** The question as it was printed. */
  statement: string;
  correct: boolean;
  difficulty: number;
  /** Already formatted by the app — the library formats no dates. */
  answeredAt: string;
  /** True for an AI-written exercise; marks it with the mandarin accent. */
  generated?: boolean;
  /** True when the teacher overrode the scanner's reading of this item. */
  corrected?: boolean;
}

export interface AttemptListLabels {
  correct: string;
  incorrect: string;
  /** "Corrected by you" — the teacher overrode the scanner. */
  corrected: string;
  difficulty: string;
  aiBadge: string;
  empty: string;
}

export interface AttemptListProps extends HTMLAttributes<HTMLDivElement> {
  attempts: AttemptRow[];
  labels: AttemptListLabels;
  /** Rendered under each row: the links back to the sheet and the scan. */
  renderProvenance?: (attempt: AttemptRow) => ReactNode;
}

/**
 * The evidence behind one matrix cell, newest first.
 *
 * A band is an argument and this is what backs it. Correctness never rides on
 * colour alone: every row carries the word as well as the mark, because the
 * green/red pair is exactly the one a colour-blind reader loses.
 */
export const AttemptList = forwardRef<HTMLDivElement, AttemptListProps>(function AttemptList(
  { attempts, labels, renderProvenance, className, ...rest },
  ref,
) {
  if (attempts.length === 0) {
    return (
      <div ref={ref} className={cx('text-body-s text-ink-500', className)} {...rest}>
        {labels.empty}
      </div>
    );
  }

  return (
    <div ref={ref} className={className} {...rest}>
      <ol className="flex list-none flex-col gap-2 p-0">
        {attempts.map((attempt) => (
          <li
            key={attempt.id}
            className="ard-panel flex flex-col gap-1"
            data-outcome={attempt.correct ? 'correct' : 'incorrect'}
          >
            <div className="flex flex-wrap items-center gap-2">
              {/* The state family, not the mastery ramp (G14).
                  These borrowed `--c-mastery-solid` and `--c-mastery-fading`,
                  and `fading` does not mean "wrong" — it means evidence has gone
                  stale, which is a different quantity measured on a different
                  scale. The ramp is a calibrated encoding of decayed competency
                  evidence and a single right-or-wrong answer is not a point on
                  it; reusing it quietly claimed they were the same measurement.
                  The word and the glyph are still there, so this reads the same
                  photocopied (DC-colour-08). */}
              <span
                className={cx(
                  'inline-flex items-center gap-1 rounded-sm border px-2 py-0.5',
                  'font-display text-label font-bold',
                  attempt.correct
                    ? 'border-success-500 bg-success-100 text-success-600'
                    : 'border-danger-500 bg-danger-100 text-danger-600',
                )}
              >
                <span aria-hidden="true">{attempt.correct ? '✓' : '✗'}</span>
                {attempt.correct ? labels.correct : labels.incorrect}
              </span>
              <time className="text-body-s text-ink-500" data-numeric="">
                {attempt.answeredAt}
              </time>
              <span className="text-body-s text-ink-500" data-numeric="">
                {labels.difficulty} {attempt.difficulty}
              </span>
              {attempt.generated ? <AiBadge label={labels.aiBadge} /> : null}
              {attempt.corrected ? (
                <span className="ard-chip text-label">{labels.corrected}</span>
              ) : null}
            </div>
            <p className="m-0 text-body-s">{attempt.statement}</p>
            {renderProvenance ? (
              <div className="flex flex-wrap gap-3 text-body-s">{renderProvenance(attempt)}</div>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
});
