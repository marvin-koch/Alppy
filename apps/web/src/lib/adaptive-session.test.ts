/**
 * What survives the tab closing (F4).
 *
 * The proposal is durable server-side; the job id that addressed it was not,
 * and neither was the teacher's own work on top of it. These pin both halves
 * of what this module promises — and, just as importantly, the one thing it
 * refuses to remember.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Uuid } from './api/types';
import { loadRun, recentRuns, rememberRun, saveRun } from './adaptive-session';

const JOB = '00000000-0000-4000-8000-0000000009a1' as Uuid;
const OTHER = '00000000-0000-4000-8000-0000000009a2' as Uuid;
const CLASS = '00000000-0000-4000-8000-000000000020';

afterEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe('a run record', () => {
  it('comes back with the moves the teacher made', () => {
    saveRun(JOB, { moves: { '7B_04': 2 }, sheetId: null, jobId: null });
    expect(loadRun(JOB).moves).toEqual({ '7B_04': 2 });
  });

  /** Two runs in one session must not read each other's overrides: a move is
   *  "this child, that group", and the groups differ between proposals. */
  it('is keyed by job, so runs cannot bleed into each other', () => {
    saveRun(JOB, { moves: { '7B_04': 2 }, sheetId: null, jobId: null });
    expect(loadRun(OTHER).moves).toEqual({});
  });

  /** The export chain's ids, so a finished render's download links come back
   *  rather than the teacher hunting for the sheet in `/sheets`. */
  it('carries an export already started', () => {
    saveRun(JOB, { moves: {}, sheetId: OTHER, jobId: JOB });
    expect(loadRun(JOB)).toMatchObject({ sheetId: OTHER, jobId: JOB });
  });

  it('reads as empty when there is nothing, and when there is no job at all', () => {
    expect(loadRun(JOB)).toEqual({ moves: {}, sheetId: null, jobId: null });
    expect(loadRun(null)).toEqual({ moves: {}, sheetId: null, jobId: null });
  });

  /** Stored shapes come from an older version of this app. A `moves` that is
   *  an array, or holds strings, is dropped rather than rendered. */
  it('refuses a stored shape it does not recognise', () => {
    window.sessionStorage.setItem(
      `alppy.adaptive.run.${JOB}`,
      JSON.stringify({ moves: ['nope'], sheetId: 12, jobId: null }),
    );
    expect(loadRun(JOB)).toEqual({ moves: {}, sheetId: null, jobId: null });

    window.sessionStorage.setItem(`alppy.adaptive.run.${JOB}`, 'not json at all');
    expect(loadRun(JOB).moves).toEqual({});
  });

  /** Safari's private mode throws on write rather than refusing quietly. A
   *  group move is not worth taking the screen down for. */
  it('survives a storage that throws', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError');
    });
    expect(() => saveRun(JOB, { moves: {}, sheetId: null, jobId: null })).not.toThrow();
  });
});

describe('recent runs', () => {
  it('lists the newest first', () => {
    rememberRun(CLASS, OTHER, '2026-09-10T08:00:00Z');
    rememberRun(CLASS, JOB, '2026-09-11T10:15:00Z');
    expect(recentRuns(CLASS).map((r) => r.jobId)).toEqual([JOB, OTHER]);
  });

  it('does not list the same run twice', () => {
    rememberRun(CLASS, JOB, '2026-09-11T10:15:00Z');
    rememberRun(CLASS, JOB, '2026-09-11T10:20:00Z');
    expect(recentRuns(CLASS)).toHaveLength(1);
    expect(recentRuns(CLASS)[0]?.startedAt).toBe('2026-09-11T10:20:00Z');
  });

  it('keeps five, not a history', () => {
    for (let i = 0; i < 9; i += 1) {
      rememberRun(CLASS, `job-${i}` as Uuid, `2026-09-1${i}T10:00:00Z`);
    }
    expect(recentRuns(CLASS)).toHaveLength(5);
  });

  /** A proposal belongs to a class. The rail can switch class under this
   *  screen, and one class's runs must not appear under another's name. */
  it('is kept per class', () => {
    rememberRun(CLASS, JOB, '2026-09-11T10:15:00Z');
    expect(recentRuns('another-class')).toEqual([]);
    expect(recentRuns(null)).toEqual([]);
  });
});
