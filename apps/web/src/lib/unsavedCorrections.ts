import type { DetectionCorrection, DetectionOut, Uuid } from '@/lib/api/types';

/**
 * Corrections the server does not have yet, kept for the life of the tab.
 *
 * The review screen already marks a correction that came back as an error. It
 * kept that record in React state, and a 401 does not leave the component
 * around to show it: the shell's unauthorized handler clears the cache and
 * `router.replace`s to the login screen within the same tick, so the teacher
 * who had just judged an answer came back from signing in to a pile with no
 * trace of it — the machine's reading on the row, and nothing to say anyone had
 * disagreed. Confirming that pile would have graded the machine's verdict.
 *
 * So the correction is written here BEFORE it is sent and removed once the
 * server agrees. That order is what makes it survive: nothing about the failure
 * path has to run for the record to exist. `sessionStorage` rather than
 * `localStorage` because this is one sitting at one machine, and a correction
 * pending on a shared classroom computer must not greet the next teacher.
 */
const PREFIX = 'alppy.unsaved-corrections.';

type Stored = [Uuid, DetectionCorrection][];

function storage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    // Blocked storage (a privacy mode, a sandboxed frame): degrade to the old
    // in-memory behaviour rather than breaking the review screen.
    return null;
  }
}

export function loadUnsaved(scanId: Uuid): Map<Uuid, DetectionCorrection> {
  const store = storage();
  if (!store) return new Map();
  try {
    const raw = store.getItem(PREFIX + scanId);
    if (!raw) return new Map();
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return new Map();
    return new Map(
      parsed.filter(
        (entry): entry is Stored[number] =>
          Array.isArray(entry) && typeof entry[0] === 'string' && typeof entry[1] === 'object',
      ),
    );
  } catch {
    return new Map();
  }
}

export function saveUnsaved(scanId: Uuid, corrections: ReadonlyMap<Uuid, DetectionCorrection>): void {
  const store = storage();
  if (!store) return;
  try {
    if (corrections.size === 0) store.removeItem(PREFIX + scanId);
    else store.setItem(PREFIX + scanId, JSON.stringify([...corrections]));
  } catch {
    // Quota or a blocked write: the row marker in memory still works.
  }
}

/**
 * Whether the server already holds what this correction asked for.
 *
 * A correction still on record when the pile comes back may have landed after
 * all — the request can succeed while the screen that sent it is being torn
 * down. Those are dropped rather than re-marked, so a teacher is never asked to
 * retry something that is already saved.
 */
export function alreadyApplied(detection: DetectionOut, body: DetectionCorrection): boolean {
  if (detection.outcome !== 'corrected') return false;
  if ('detected_index' in body && body.detected_index !== detection.detected_index) return false;
  if ('verdict_correct' in body && body.verdict_correct !== detection.verdict_correct) return false;
  if (body.transcription != null && body.transcription !== detection.transcription) return false;
  return true;
}
