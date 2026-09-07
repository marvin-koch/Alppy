import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { toPercent } from '../../lib/geometry';
import type { MasteryBand } from '../../lib/mastery';
import { BandGlyph } from './MasteryCell';

export interface MasteryMeterProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  band: MasteryBand;
  /** 0..1, or null when the competency was never assessed. */
  score: number | null;
  /** The band's name in the teacher's language — the app supplies it. */
  bandLabel: string;
  /**
   * The line after the band, e.g. "62 % · révision dans 2 jours". The library
   * formats no numbers and translates no words; pass the whole caption.
   */
  caption?: ReactNode;
  /** Show the raw percentage numeral next to the label. */
  showScore?: boolean;
}

/**
 * The band gauge (DESIGN.md §6): a pill carrying the band glyph, the band label
 * and a caption. Three channels — colour, tint density, and words — so it
 * survives the photocopier and colour-blind readers alike.
 *
 * The second channel is the SAME glyph the matrix draws (disc 4/4 · 3/4 · 2/4 ·
 * 1/4 · dashed ring). It used to be `.ard-mastery-dot`, a plain filled circle
 * identical in shape for all five bands — which taught a second, weaker
 * vocabulary for the same scale and carried no information without colour.
 */
export const MasteryMeter = forwardRef<HTMLDivElement, MasteryMeterProps>(function MasteryMeter(
  { band, score, bandLabel, caption, showScore = true, className, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('flex flex-wrap items-center gap-2', className)} {...rest}>
      <span className="ard-mastery" data-band={band}>
        <BandGlyph band={band} size={13} />
        {bandLabel}
        {showScore && score !== null ? (
          <span data-numeric="" className="tabular-nums opacity-80">
            {toPercent(score)}
          </span>
        ) : null}
      </span>
      {caption ? <span className="text-body-s text-ink-500">{caption}</span> : null}
    </div>
  );
});
