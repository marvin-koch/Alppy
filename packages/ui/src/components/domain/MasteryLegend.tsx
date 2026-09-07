import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../../lib/cx';
import type { BandLabels, MasteryBand } from '../../lib/mastery';
import { BandGlyph } from './MasteryCell';

const BAND_ORDER: MasteryBand[] = ['solid', 'ok', 'weak', 'fading', 'none'];

/* The same tint/ink/edge triple the cells use, so a legend swatch and the cell
   it explains are literally the same object at a different size. Reading these
   from the same tokens is the point: a legend painted from its own palette
   stops matching the grid the moment a theme overrides a band. */
const SWATCH: Record<MasteryBand, string> = {
  solid: 'bg-[var(--c-mastery-solid-tint)] text-[var(--c-mastery-solid-ink)] border-[var(--c-mastery-solid)]',
  ok: 'bg-[var(--c-mastery-ok-tint)] text-[var(--c-mastery-ok-ink)] border-[var(--c-mastery-ok)]',
  weak: 'bg-[var(--c-mastery-weak-tint)] text-[var(--c-mastery-weak-ink)] border-[var(--c-mastery-weak)]',
  fading: 'bg-[var(--c-mastery-fading-tint)] text-[var(--c-mastery-fading-ink)] border-[var(--c-mastery-fading)]',
  none: 'bg-[var(--c-mastery-none-tint)] text-[var(--c-mastery-none-ink)] border-[var(--c-mastery-none)]',
};

export interface MasteryLegendProps extends HTMLAttributes<HTMLUListElement> {
  /** One label per band, in the teacher's language. */
  bandLabels: BandLabels;
  /** Optional threshold explanation per band ("Mastered — at least 90 %"). */
  bandHelp?: Partial<Record<MasteryBand, string>>;
}

/**
 * The key to the matrix.
 *
 * This has to carry the *same three channels the cells carry* — tint, glyph and
 * word — or it explains nothing. A legend of plain text chips names five bands
 * without saying which cell is which, which is the one job a legend has; that
 * is what shipped, under a comment claiming the opposite.
 */
export const MasteryLegend = forwardRef<HTMLUListElement, MasteryLegendProps>(
  function MasteryLegend({ bandLabels, bandHelp, className, ...rest }, ref) {
    return (
      <ul
        ref={ref}
        className={cx('flex list-none flex-wrap gap-2 p-0', className)}
        {...rest}
      >
        {BAND_ORDER.map((band) => (
          <li key={band}>
            <span
              data-band={band}
              title={bandHelp?.[band]}
              className={cx(
                'inline-flex items-center gap-1.5 rounded-sm border px-2 py-1',
                'font-display text-label font-bold',
                SWATCH[band],
              )}
            >
              <BandGlyph band={band} />
              {bandLabels[band]}
            </span>
            {bandHelp?.[band] ? (
              <span className="visually-hidden">{bandHelp[band]}</span>
            ) : null}
          </li>
        ))}
      </ul>
    );
  },
);
