/**
 * What a differentiation run leaves behind when the tab closes.
 *
 * The proposal itself is durable — `GET /adaptive/proposal/{job_id}` returns it
 * and the query pins `staleTime: Infinity` for exactly that reason. What was
 * lost was the *job id that addresses it*, which existed only in one
 * component's `useState`. M. Rossier presses **Proposer** at 10:15, the bell
 * goes at 10:40, he closes the laptop; the job finishes at 10:47 and there is
 * no way back to it. Reopening `/adaptive` offers him the empty state and a
 * button that would spend twenty-four more provider calls rebuilding what
 * already exists.
 *
 * The job id now lives in the URL (`/adaptive?job=…`), the way the scan flow
 * has always done it. This module holds the two things the URL cannot:
 *
 *  · **the run record** — what the teacher changed about a proposal that the
 *    server has not been told about yet. `sessionStorage`, keyed by job id.
 *  · **the recent runs** — so a teacher who lost the tab entirely has somewhere
 *    to look. `localStorage`, keyed by class.
 *
 * Deliberately NOT stored: which exercises are approved. `adaptive/page.tsx`
 * says why in the line that declares it — approval is a fact about the
 * database, not about this browser tab, and the export gate reads it. Restoring
 * it from storage could open that gate on the word of a tab. A recovered run
 * therefore shows its generated exercises as unapproved until the server says
 * otherwise, which is the safe direction to be wrong in. Making it *right*
 * needs a read the API does not have yet (see the note in `page.tsx`).
 *
 * Every access is wrapped: Safari's private mode throws on `localStorage`
 * rather than returning null, and a page that cannot remember a preference must
 * still render.
 */

import type { Uuid } from './api/types';

const RUN_PREFIX = 'alppy.adaptive.run.';
const RECENT_PREFIX = 'alppy.adaptive.recent.';

/** More than a teacher would ever scroll, few enough to stay one glance. */
const RECENT_LIMIT = 5;

/** The teacher's own work on a proposal, none of which the server knows. */
export interface AdaptiveRun {
  /** Teacher overrides: student uid -> group index. */
  moves: Record<string, number>;
  /** The sheet the export created, if it got that far. */
  sheetId: Uuid | null;
  /** The render job for that sheet, so the download links can come back. */
  jobId: Uuid | null;
}

export interface RecentRun {
  jobId: Uuid;
  /** ISO, written here rather than read from the job: this list has to render
   *  before anything is fetched. */
  startedAt: string;
}

const EMPTY_RUN: AdaptiveRun = { moves: {}, sheetId: null, jobId: null };

function read(store: Storage | undefined, key: string): unknown {
  try {
    const raw = store?.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function write(store: Storage | undefined, key: string, value: unknown): void {
  try {
    store?.setItem(key, JSON.stringify(value));
  } catch {
    /* Full, or blocked. Losing a group move is not worth failing a render. */
  }
}

function session(): Storage | undefined {
  return typeof window === 'undefined' ? undefined : window.sessionStorage;
}

function local(): Storage | undefined {
  return typeof window === 'undefined' ? undefined : window.localStorage;
}

export function loadRun(jobId: Uuid | null): AdaptiveRun {
  if (!jobId) return EMPTY_RUN;
  const raw = read(session(), RUN_PREFIX + jobId);
  if (raw === null || typeof raw !== 'object') return EMPTY_RUN;
  const record = raw as Partial<AdaptiveRun>;
  return {
    // A stored shape is a shape from a previous version of this app. Anything
    // that is not what we expect is dropped rather than trusted into a render.
    moves: isMoves(record.moves) ? record.moves : {},
    sheetId: typeof record.sheetId === 'string' ? (record.sheetId as Uuid) : null,
    jobId: typeof record.jobId === 'string' ? (record.jobId as Uuid) : null,
  };
}

export function saveRun(jobId: Uuid | null, run: AdaptiveRun): void {
  if (!jobId) return;
  write(session(), RUN_PREFIX + jobId, run);
}

function isMoves(value: unknown): value is Record<string, number> {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    Object.values(value).every((entry) => typeof entry === 'number')
  );
}

export function recentRuns(classId: string | null): RecentRun[] {
  if (!classId) return [];
  const raw = read(local(), RECENT_PREFIX + classId);
  if (!Array.isArray(raw)) return [];
  return raw
    .filter(
      (entry): entry is RecentRun =>
        typeof entry === 'object' &&
        entry !== null &&
        typeof (entry as RecentRun).jobId === 'string' &&
        typeof (entry as RecentRun).startedAt === 'string',
    )
    .slice(0, RECENT_LIMIT);
}

/** Newest first, de-duplicated, capped. Called when a run is started. */
export function rememberRun(classId: string | null, jobId: Uuid, startedAt: string): void {
  if (!classId) return;
  const next = [
    { jobId, startedAt },
    ...recentRuns(classId).filter((entry) => entry.jobId !== jobId),
  ].slice(0, RECENT_LIMIT);
  write(local(), RECENT_PREFIX + classId, next);
}
