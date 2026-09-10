import { describe, expect, it } from 'vitest';

import { aggregatePoints, averageRatio, pointsRatio, type PointsSummary } from './points';

/**
 * "A blank is never penalised, and an ungraded pile is never a zero."
 *
 * `earned: null` means *not marked yet*. Every bug this file guards against
 * has the same shape — null coerced to 0 somewhere — and the same symptom: a
 * child, or a whole class, shown as having failed work nobody has looked at.
 * The rule is stated once in points.ts precisely so it cannot be remembered in
 * one screen and forgotten in another; these pin it.
 */
const graded = (earned: number, possible: number): PointsSummary => ({ earned, possible });
const ungraded = (possible: number): PointsSummary => ({ earned: null, possible });

describe('pointsRatio', () => {
  it('divides a graded result', () => {
    expect(pointsRatio(graded(7, 10))).toBeCloseTo(0.7);
  });

  it('is null when nothing has been graded — never 0', () => {
    expect(pointsRatio(ungraded(10))).toBeNull();
  });

  it('is null rather than Infinity or NaN when there is nothing to divide by', () => {
    expect(pointsRatio(graded(0, 0))).toBeNull();
    expect(pointsRatio(graded(3, 0))).toBeNull();
  });

  it('keeps a real zero distinct from an absent one', () => {
    // A child who genuinely scored 0 out of 10 IS a 0. The rule is about the
    // unmarked pile, and conflating the two in either direction is the bug.
    expect(pointsRatio(graded(0, 10))).toBe(0);
    expect(pointsRatio(ungraded(10))).toBeNull();
  });
});

describe('aggregatePoints', () => {
  it('sums the graded entries', () => {
    expect(aggregatePoints([graded(7, 10), graded(8, 10)])).toEqual({ earned: 15, possible: 20 });
  });

  /**
   * The load-bearing one. An unmarked sheet must not enlarge the denominator:
   * a term with two of five sheets marked must not read as three failures.
   */
  it('does not let an unmarked sheet enlarge the denominator', () => {
    const total = aggregatePoints([graded(9, 10), ungraded(10), ungraded(10)]);
    expect(total).toEqual({ earned: 9, possible: 10 });
    expect(pointsRatio(total)).toBe(0.9);
  });

  it('is null, not 0/0, when nothing in the set is graded', () => {
    const total = aggregatePoints([ungraded(10), ungraded(20)]);
    expect(total.earned).toBeNull();
    expect(pointsRatio(total)).toBeNull();
  });

  it('is null for an empty set', () => {
    expect(aggregatePoints([]).earned).toBeNull();
  });
});

describe('averageRatio', () => {
  it('averages each entry’s own ratio, so a long sheet does not outweigh a short one', () => {
    // Summing first would give 11/20 = 0.55; averaging ratios gives 0.75.
    expect(averageRatio([graded(1, 10), graded(10, 10)])).toBeCloseTo(0.55);
    expect(averageRatio([graded(5, 10), graded(10, 10)])).toBeCloseTo(0.75);
  });

  it('ignores the ungraded rather than counting them as zero', () => {
    expect(averageRatio([graded(8, 10), ungraded(10)])).toBeCloseTo(0.8);
  });

  it('is null when no entry is graded', () => {
    expect(averageRatio([ungraded(10), ungraded(10)])).toBeNull();
    expect(averageRatio([])).toBeNull();
  });
});
