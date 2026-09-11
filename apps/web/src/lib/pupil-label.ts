/**
 * How a pupil is named on screen, and nothing else.
 *
 * Its own module, with no React and no navigation in it, so the one decision
 * projector mode makes can be imported (and tested) without dragging in the
 * context, the attribute observer and next-intl's router. `lib/discreet.tsx`
 * re-exports it, so callers still have one import path.
 */

import { studentName } from './studentName';

/**
 * Nullable, because `StudentOut` is: answering a parent's erasure request nulls
 * both names and keeps the row (`anonymised_at`). The narrower non-null shape
 * this replaces could not accept a real `StudentOut` at all, which is part of why
 * this function had no production caller until now — and why the one screen that
 * formatted a pupil's name by hand rendered a literal `"null null"` for an
 * anonymised pupil.
 */
export interface Pupil {
  uid: string;
  first_name: string | null;
  last_name: string | null;
}

/**
 * The UID rather than initials, a blur or a redaction block: it is the
 * identifier already printed on that child's own paper, so the teacher can
 * resolve it from the pile in their hand, and it is meaningless to everyone
 * else in the room. The screen stays exactly as usable as it was.
 *
 * The visible case goes through `studentName`, so the two answers to "what goes
 * where a pupil's name goes" cannot drift apart: both fall back to the uid, and
 * for the same reason.
 */
export function pupilLabel(pupil: Pupil, hideNames: boolean): string {
  if (hideNames) return pupil.uid;
  return studentName(pupil);
}
