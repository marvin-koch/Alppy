import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cx } from '../../lib/cx';
import { toPercent } from '../../lib/geometry';
import type { MasteryBand } from '../../lib/mastery';

/* Tint density AND ink come from the band tokens; the glyph is the third
   channel, so the cell still reads on a photocopy or without colour vision. */
const CELL_TINT: Record<MasteryBand, string> = {
  solid: 'bg-[var(--c-mastery-solid-tint)] text-[var(--c-mastery-solid-ink)] border-[var(--c-mastery-solid)]',
  ok: 'bg-[var(--c-mastery-ok-tint)] text-[var(--c-mastery-ok-ink)] border-[var(--c-mastery-ok)]',
  weak: 'bg-[var(--c-mastery-weak-tint)] text-[var(--c-mastery-weak-ink)] border-[var(--c-mastery-weak)]',
  fading: 'bg-[var(--c-mastery-fading-tint)] text-[var(--c-mastery-fading-ink)] border-[var(--c-mastery-fading)]',
  none: 'bg-[var(--c-mastery-none-tint)] text-[var(--c-mastery-none-ink)] border-[var(--c-mastery-none)]',
};

export interface BandGlyphProps {
  band: MasteryBand;
  size?: number;
  className?: string;
}

/**
 * A density ramp — full · half · ringed · hollow · dash — so the five bands are
 * distinguishable with no colour at all.
 */
export function BandGlyph({ band, size = 12, className }: BandGlyphProps) {
  return (
    <svg
      viewBox="0 0 12 12"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
      focusable="false"
      className={cx('shrink-0', className)}
    >
      {band === 'solid' ? <circle cx="6" cy="6" r="4.6" fill="currentColor" stroke="none" /> : null}
      {band === 'ok' ? (
        <>
          <circle cx="6" cy="6" r="4.4" />
          <path d="M6 1.6a4.4 4.4 0 0 0 0 8.8Z" fill="currentColor" stroke="none" />
        </>
      ) : null}
      {band === 'weak' ? (
        <>
          <circle cx="6" cy="6" r="4.4" />
          <circle cx="6" cy="6" r="1.6" fill="currentColor" stroke="none" />
        </>
      ) : null}
      {band === 'fading' ? <circle cx="6" cy="6" r="4.4" strokeDasharray="2.2 1.8" /> : null}
      {band === 'none' ? <path d="M2.4 6h7.2" strokeLinecap="round" /> : null}
    </svg>
  );
}

export interface MasteryCellLabelParts {
  studentName: string;
  competencyLabel: string;
  bandLabel: string;
  score: number | null;
}

export interface MasteryCellProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'value' | 'aria-label' | 'type'> {
  band: MasteryBand;
  /** 0..1, or null when never assessed. */
  score: number | null;
  /** Used only to build the accessible name. */
  studentName: string;
  competencyLabel: string;
  /** The band in the teacher's language — the app supplies it. */
  bandLabel: string;
  /**
   * Builds the accessible name. The default joins student · competency · band
   * (· score) with a separator character, so no translated word is needed.
   */
  formatLabel?: (parts: MasteryCellLabelParts) => string;
  showScore?: boolean;
  selected?: boolean;
}

function defaultLabel({ studentName, competencyLabel, bandLabel, score }: MasteryCellLabelParts): string {
  const parts = [studentName, competencyLabel, bandLabel];
  if (score !== null) parts.push(`${toPercent(score)} %`);
  return parts.join(' · ');
}

/**
 * One cell of the matrix, and a real `<button>`: every cell drills down to the
 * attempts behind it. Its accessible name always names the student, the
 * competency AND the band — a screen-reader user must never be asked to
 * interpret a colour.
 */
export const MasteryCell = forwardRef<HTMLButtonElement, MasteryCellProps>(function MasteryCell(
  {
    band,
    score,
    studentName,
    competencyLabel,
    bandLabel,
    formatLabel = defaultLabel,
    showScore = true,
    selected = false,
    className,
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      data-band={band}
      aria-label={formatLabel({ studentName, competencyLabel, bandLabel, score })}
      aria-pressed={selected}
      className={cx(
        'flex h-11 w-full min-w-11 items-center justify-center gap-1 rounded-sm border',
        'font-display text-body-s font-bold tabular-nums transition-transform',
        'hover:-translate-y-px',
        CELL_TINT[band],
        selected && 'shadow-[var(--focus-ring)]',
        className,
      )}
      {...rest}
    >
      <BandGlyph band={band} />
      {showScore && score !== null ? <span data-numeric="">{toPercent(score)}</span> : null}
    </button>
  );
});
