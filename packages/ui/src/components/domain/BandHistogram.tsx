import { cx } from '../../lib/cx';
import { BAND_ORDER, type BandLabels, type MasteryBand } from '../../lib/mastery';
import { BandGlyph } from './MasteryCell';

export interface BandHistogramProps {
  /** How many (student × competency) cells sit in each band. */
  counts: Partial<Record<MasteryBand, number>>;
  /** The written band names. Required — the bar is never read by colour. */
  labels: BandLabels;
  /** Accessible summary, e.g. "18 élèves, 7 compétences". */
  label: string;
  className?: string;
}

/**
 * The SHAPE of a class in one bar: every band, in order, sized by how many
 * cells sit in it.
 *
 * Not an average, and deliberately not a number. A class mean would collapse
 * "half mastered, half fading" and "everyone middling" onto the same figure,
 * and those are different rooms to walk into.
 *
 * Built here rather than in a chart library for the reason `MasteryCurve`
 * gives: it is a hundred lines of flexbox, it prints, and it costs no runtime
 * dependency. Three channels as everywhere else — the segment's calibrated
 * tint, the glyph, and the written word in the legend beneath (DC-colour-08).
 * A segment on its own would be an anonymous colour.
 */
export function BandHistogram({ counts, labels, label, className }: BandHistogramProps) {
  const present = BAND_ORDER.filter((band) => (counts[band] ?? 0) > 0);
  const total = present.reduce((sum, band) => sum + (counts[band] ?? 0), 0);

  if (total === 0) return null;

  return (
    <div className={cx('flex flex-col gap-2', className)}>
      <div
        className="flex h-2.5 overflow-hidden rounded-pill"
        role="img"
        aria-label={label}
      >
        {present.map((band) => (
          <span
            key={band}
            data-band={band}
            title={`${labels[band]} : ${counts[band] ?? 0}`}
            // The band's own calibrated colour, not the tint: at 10px high a
            // tint over white is too pale to separate from its neighbour.
            className="ard-band-bar h-full"
            style={{ width: `${((counts[band] ?? 0) / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className="flex list-none flex-wrap gap-3.5 p-0">
        {present.map((band) => (
          <li key={band} className="flex items-center gap-1.5">
            <span className={cx('ard-band-ink')} data-band={band}>
              <BandGlyph band={band} size={12} />
            </span>
            <span className="text-label text-ink-500">
              {labels[band]} {counts[band] ?? 0}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
