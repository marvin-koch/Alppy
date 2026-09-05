/**
 * The ordered domain scale (DESIGN.md §2). Five bands, one order, everywhere.
 *
 * The library carries NO translated strings: every component that shows a band
 * takes its label as a prop. `BAND_ORDER` fixes the order (best → worst) so a
 * legend, a matrix header and a print key can never disagree.
 */
export type MasteryBand = 'solid' | 'ok' | 'weak' | 'fading' | 'none';

export const BAND_ORDER = ['solid', 'ok', 'weak', 'fading', 'none'] as const satisfies readonly MasteryBand[];

/** Lower bound of each scored band (docs/plan.md §6). `none` = never assessed. */
export const BAND_THRESHOLDS = {
  solid: 0.9,
  ok: 0.75,
  weak: 0.6,
  fading: 0,
} as const;

/**
 * Band for a score in [0,1]. `null`/`undefined` (never assessed) → 'none'.
 * The server is authoritative; this mirrors it for optimistic UI only.
 */
export function bandForScore(score: number | null | undefined): MasteryBand {
  if (score === null || score === undefined || Number.isNaN(score)) return 'none';
  if (score >= BAND_THRESHOLDS.solid) return 'solid';
  if (score >= BAND_THRESHOLDS.ok) return 'ok';
  if (score >= BAND_THRESHOLDS.weak) return 'weak';
  return 'fading';
}

/** A band label supplied by the app, one entry per band. No defaults, by design. */
export type BandLabels = Record<MasteryBand, string>;
