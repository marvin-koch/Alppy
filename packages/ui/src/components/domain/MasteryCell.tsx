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
 * The band glyph — the third channel, independent of colour.
 *
 * Geometry transcribed from the shipped brand library
 * (`docs/design/alppy-brand-assets/brand/mastery/`), not invented: a disc of
 * radius 8.624 on a 44-unit grid, filled in quarters, with a constant ring so
 * the outline reads the same at every band.
 *
 *   solid  full disc        ok  3/4        weak  2/4
 *   fading 1/4              none  dashed ring, no fill
 *
 * A quarter-turn per band is deliberately coarse: it survives a photocopy and a
 * 12px rendering, which a subtle density ramp does not.
 */
export function BandGlyph({ band, size = 12, className }: BandGlyphProps) {
  // Pie wedges, all starting at 12 o'clock and sweeping clockwise.
  const WEDGE: Partial<Record<MasteryBand, string>> = {
    ok: 'M22 22L22 13.376A8.624 8.624 0 1 1 13.376 22Z',
    weak: 'M22 22L22 13.376A8.624 8.624 0 0 1 22 30.624Z',
    fading: 'M22 22L22 13.376A8.624 8.624 0 0 1 30.624 22Z',
  };

  return (
    <svg
      viewBox="0 0 44 44"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      aria-hidden="true"
      focusable="false"
      className={cx('shrink-0', className)}
    >
      {band === 'solid' ? (
        <circle cx="22" cy="22" r="8.624" fill="currentColor" stroke="none" />
      ) : null}
      {WEDGE[band] ? <path d={WEDGE[band]} fill="currentColor" stroke="none" /> : null}
      <circle
        cx="22"
        cy="22"
        r="8.624"
        strokeWidth="1.9"
        strokeLinecap="round"
        {...(band === 'none' ? { strokeDasharray: '2.6 3.4' } : {})}
      />
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
