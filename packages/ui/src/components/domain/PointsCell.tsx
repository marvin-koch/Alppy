import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cx } from '../../lib/cx';
import { toPercent } from '../../lib/geometry';

export interface PointsCellLabelParts {
  studentName: string;
  columnLabel: string;
  earned: number | null;
  possible: number;
  graded: boolean;
}

export interface PointsCellProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'value' | 'onSelect'> {
  /** null = nothing graded yet. NOT zero. */
  earned: number | null;
  possible: number;
  studentName: string;
  columnLabel: string;
  /** Builds the accessible sentence — the app owns the wording and the locale. */
  formatLabel: (parts: PointsCellLabelParts) => string;
  /** The running-total column, which is a summary rather than one more sheet. */
  emphasized?: boolean;
  selected?: boolean;
}

/**
 * One score in a points matrix.
 *
 * Deliberately NOT a `MasteryCell`. The five-band ramp is a calibrated encoding
 * of decayed competency evidence — greyscale-monotonic, constant glyph
 * luminance — and a raw score is a different measurement. Colouring 71 % amber
 * would silently assert "this pupil is fragile at this competency", a claim the
 * mastery model never made and that a single bad morning does not support. So a
 * score gets a neutral face and states its number.
 *
 * Two states, and the glyph carries them, not the colour: a graded cell shows a
 * percentage, an ungraded one shows an em dash. Never a `0 %` for a copy nobody
 * has marked — that is a claim about a pupil who has not been assessed.
 */
export const PointsCell = forwardRef<HTMLButtonElement, PointsCellProps>(function PointsCell(
  {
    earned,
    possible,
    studentName,
    columnLabel,
    formatLabel,
    emphasized = false,
    selected = false,
    className,
    ...rest
  },
  ref,
) {
  const graded = earned !== null;
  const ratio = graded && possible > 0 ? earned / possible : null;
  return (
    <button
      ref={ref}
      type="button"
      data-graded={graded ? 'true' : 'false'}
      aria-label={formatLabel({ studentName, columnLabel, earned, possible, graded })}
      aria-pressed={selected}
      className={cx(
        'flex h-11 w-full min-w-11 items-center justify-center rounded-sm border',
        'font-display text-body-s font-bold tabular-nums transition-transform',
        'hover:-translate-y-px',
        graded
          ? 'border-line bg-surface-2 text-ink-900'
          : 'border-dashed border-line-strong bg-surface-2 text-ink-300',
        emphasized && 'border-primary-200 bg-primary-050 text-primary-700',
        selected && 'shadow-[var(--focus-ring)]',
        className,
      )}
      {...rest}
    >
      <span data-numeric="">{ratio === null ? '—' : toPercent(ratio)}</span>
    </button>
  );
});
