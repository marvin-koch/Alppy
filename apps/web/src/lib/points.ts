/**
 * Points, and the one rule that governs every screen showing them.
 *
 * `earned` is `null` when nothing has been graded. That is **not** zero, and
 * the difference is the whole reason this file exists rather than being three
 * inline ternaries: a term where two of five sheets are marked must not read
 * as three failures, and a pile nobody has scanned must not show a class
 * average of 0%. Every surface goes through here so the rule cannot be
 * remembered in one place and forgotten in another.
 */

export interface PointsSummary {
  /** null = not graded yet. Never render as 0. */
  earned: number | null;
  possible: number;
}

/** The ratio 0..1, or null when there is nothing to divide. */
export function pointsRatio(points: PointsSummary): number | null {
  if (points.earned === null || points.possible <= 0) return null;
  return points.earned / points.possible;
}

/**
 * Sum a set of results into one.
 *
 * `possible` accumulates over the graded entries only — an unmarked sheet must
 * not enlarge the denominator and drag the ratio down as though it had been
 * failed. The total of an unmarked term is `null`, not `0 / 30`.
 */
export function aggregatePoints(entries: readonly PointsSummary[]): PointsSummary {
  const graded = entries.filter((entry) => entry.earned !== null);
  if (graded.length === 0) return { earned: null, possible: 0 };
  return {
    earned: graded.reduce((sum, entry) => sum + (entry.earned ?? 0), 0),
    possible: graded.reduce((sum, entry) => sum + entry.possible, 0),
  };
}

/** The mean of each entry's own ratio, ignoring the ungraded. Null when none
 *  are graded. Averaging ratios rather than dividing the sums keeps a long
 *  sheet from outweighing a short one when the question is "how did they do". */
export function averageRatio(entries: readonly PointsSummary[]): number | null {
  const ratios = entries.map(pointsRatio).filter((r): r is number => r !== null);
  if (ratios.length === 0) return null;
  return ratios.reduce((sum, r) => sum + r, 0) / ratios.length;
}
