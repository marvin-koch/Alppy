import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { BAND_ORDER, BAND_THRESHOLDS, bandForScore, type MasteryBand } from './mastery';

/**
 * `bandForScore` is a MIRROR of `alppy.mastery.model.band_for`, kept for
 * optimistic UI while the server round-trips. A mirror that drifts is worse
 * than no mirror: the teacher sees a band flicker from one colour to another
 * on every load, and the one that is wrong is the one they read first.
 *
 * So the thresholds are asserted against the Python source of truth rather
 * than against a copy of themselves. `layout.generated.ts` solves the same
 * problem by generating the TypeScript; the bands are three numbers and have
 * not earned a generator, but they have earned a test that fails when someone
 * changes one on only one side.
 */
const MODEL_PY = join(
  __dirname,
  '../../../../apps/api/alppy/mastery/model.py',
);

function pythonThreshold(name: string): number {
  const source = readFileSync(MODEL_PY, 'utf8');
  const match = source.match(new RegExp(`^${name}:\\s*Final\\s*=\\s*([0-9.]+)`, 'm'));
  if (!match) throw new Error(`${name} not found in ${MODEL_PY}`);
  return Number(match[1]);
}

describe('the band scale mirrors the server', () => {
  it.each([
    ['BAND_SOLID', 'solid'],
    ['BAND_OK', 'ok'],
    ['BAND_WEAK', 'weak'],
  ] as const)('%s equals BAND_THRESHOLDS.%s', (pyName, tsKey) => {
    expect(BAND_THRESHOLDS[tsKey]).toBe(pythonThreshold(pyName));
  });

  it('orders the bands best to worst, with no band missing', () => {
    expect(BAND_ORDER).toEqual(['solid', 'ok', 'weak', 'fading', 'none']);
  });

  it('is monotonic: a higher score never yields a worse band', () => {
    const rank = (b: MasteryBand) => BAND_ORDER.indexOf(b);
    let previous = rank(bandForScore(0));
    for (let score = 0; score <= 1.0001; score += 0.01) {
      const current = rank(bandForScore(score));
      expect(current).toBeLessThanOrEqual(previous);
      previous = current;
    }
  });
});

describe('bandForScore', () => {
  it.each([
    [1, 'solid'],
    [0.9, 'solid'],
    [0.899, 'ok'],
    [0.75, 'ok'],
    [0.749, 'weak'],
    [0.6, 'weak'],
    [0.599, 'fading'],
    [0, 'fading'],
  ] as const)('%s -> %s', (score, band) => {
    expect(bandForScore(score)).toBe(band);
  });

  /**
   * The safety rule, in the smallest place it appears. "Never assessed" is not
   * "assessed and failed": a competency nobody has tested must read as `none`,
   * not as the worst scored band. Coercing null to 0 here would paint a fresh
   * class entirely `fading`.
   */
  it.each([null, undefined, Number.NaN])('%s is never-assessed, not zero', (value) => {
    expect(bandForScore(value as number | null | undefined)).toBe('none');
    expect(bandForScore(value as number | null | undefined)).not.toBe('fading');
  });
});
