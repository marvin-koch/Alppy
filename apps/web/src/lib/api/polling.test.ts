/**
 * Polling widens, and it stops.
 *
 * `useJob` and `useScan` polled at a flat interval with no ceiling, so a job that
 * never reached a terminal state polled for as long as the tab stayed open — and
 * the screen showed a spinner the whole time, which reads as "still working"
 * rather than "nothing is coming" (G10).
 *
 * The schedule is tested as a pure function because the thing worth pinning is the
 * shape of it: fast while a teacher is watching, slow once nobody is, and false
 * eventually. Testing it through the hook would need fake timers and a
 * QueryClient, and would pin react-query's behaviour rather than this decision.
 */

import { describe, expect, it } from 'vitest';

import { POLL_CEILING_MS, pollIntervalFor } from './queries';

describe('the poll schedule', () => {
  it('is fast while a teacher is actually watching', () => {
    expect(pollIntervalFor(0)).toBe(900);
    expect(pollIntervalFor(14_999)).toBe(900);
  });

  it('widens once the first seconds have passed', () => {
    expect(pollIntervalFor(15_000)).toBe(3_000);
    expect(pollIntervalFor(59_999)).toBe(3_000);
  });

  it('widens again once nobody is watching a progress ring', () => {
    expect(pollIntervalFor(60_000)).toBe(10_000);
    expect(pollIntervalFor(599_999)).toBe(10_000);
  });

  /** The point of the whole thing: it ends. */
  it('gives up at the ceiling', () => {
    expect(pollIntervalFor(POLL_CEILING_MS)).toBe(false);
    expect(pollIntervalFor(POLL_CEILING_MS + 60_000)).toBe(false);
  });

  it('never narrows as time passes', () => {
    let previous = 0;
    for (let t = 0; t < POLL_CEILING_MS; t += 5_000) {
      const interval = pollIntervalFor(t);
      expect(interval).not.toBe(false);
      expect(interval as number).toBeGreaterThanOrEqual(previous);
      previous = interval as number;
    }
  });

  /** Ten minutes. Long enough that a slow render or a busy worker finishes,
   *  short enough that a teacher is not left watching a dead spinner. */
  it('waits about ten minutes before giving up', () => {
    expect(POLL_CEILING_MS).toBe(600_000);
  });
});
