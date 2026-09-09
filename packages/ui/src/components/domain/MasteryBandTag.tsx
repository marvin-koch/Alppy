import type { HTMLAttributes } from 'react';

import { cx } from '../../lib/cx';
import type { MasteryBand } from '../../lib/mastery';
import { BandGlyph } from './MasteryCell';

export interface MasteryBandTagProps extends HTMLAttributes<HTMLSpanElement> {
  band: MasteryBand;
  /** The written band name. Required — see the note below. */
  label: string;
  /**
   * What the band is made of, when it is an aggregate: "2 of 3 competences
   * assessed". A rolled-up band is the one place a reader most needs this,
   * because green over one assessed competency and green over three look
   * identical without it.
   */
  caption?: string;
}

/**
 * A band as it reads outside a matrix cell — on a Theme, a Competence or a
 * Branch.
 *
 * Three channels, never fewer (DC-colour-08): the calibrated tint, the band
 * glyph, and the written word. `label` is a required prop rather than an
 * optional one for exactly that reason — a caller must not be able to produce
 * a bare coloured pill by leaving an argument out, which is how the rule
 * erodes in practice.
 *
 * The colours come from `.ard-mastery` in recipes.css, so this shares the
 * shipped calibration with `MasteryCell` rather than re-deriving it.
 */
export function MasteryBandTag({
  band,
  label,
  caption,
  className,
  ...rest
}: MasteryBandTagProps) {
  return (
    <span
      // `min-w-0` + wrapping, NOT `shrink-0`: with a coverage caption this tag
      // is wide, and in a narrow column an unshrinkable one pushes its
      // siblings to zero width and overflows the card.
      className={cx('ard-mastery min-w-0 flex-wrap', className)}
      data-band={band}
      {...rest}
    >
      <BandGlyph band={band} size={14} />
      <span>{label}</span>
      {caption ? (
        <span className="font-normal opacity-80">· {caption}</span>
      ) : null}
    </span>
  );
}
