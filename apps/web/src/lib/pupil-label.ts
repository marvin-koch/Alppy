/**
 * How a pupil is named on screen, and nothing else.
 *
 * Its own module, with no React and no navigation in it, so the one decision
 * projector mode makes can be imported (and tested) without dragging in the
 * context, the attribute observer and next-intl's router. `lib/discreet.tsx`
 * re-exports it, so callers still have one import path.
 */

export interface Pupil {
  uid: string;
  first_name: string;
  last_name: string;
}

/**
 * The UID rather than initials, a blur or a redaction block: it is the
 * identifier already printed on that child's own paper, so the teacher can
 * resolve it from the pile in their hand, and it is meaningless to everyone
 * else in the room. The screen stays exactly as usable as it was.
 */
export function pupilLabel(pupil: Pupil, hideNames: boolean): string {
  if (hideNames) return pupil.uid;
  return `${pupil.first_name} ${pupil.last_name}`.trim();
}
