/**
 * What to show where a pupil's name goes.
 *
 * A pupil can have no name: answering a parent's erasure request anonymises
 * them, which nulls the names and keeps everything else (`anonymised_at` on
 * `StudentOut`). The record stays, the class statistics keep their shape, and
 * the pupil is still sitting in the class — so a roster must still show a row
 * for them, and that row must still be identifiable to the teacher holding
 * their paper.
 *
 * The fallback is the uid, deliberately, and not a translated "anonymised
 * pupil": the uid is retained precisely because it is what the printed sheet
 * carries, it is the same string in all three locales, and it is what the
 * teacher can match against the copy in their hand. A blank would be worse
 * than either — a nameless row that looks like a rendering bug.
 */

interface Named {
  uid: string;
  first_name: string | null;
  last_name: string | null;
}

/** "Léa Roth", or "7B_15" for a pupil with no name. */
export function studentName(student: Named): string {
  return `${student.first_name ?? ''} ${student.last_name ?? ''}`.trim() || student.uid;
}

/** "ROTH Léa" — the order a roster is read and sorted in. */
export function studentSortName(student: Named): string {
  const last = (student.last_name ?? '').toUpperCase();
  return `${last} ${student.first_name ?? ''}`.trim() || student.uid;
}

/** The two halves a matrix column renders separately. The surname carries the
 *  uid fallback, because that is the half those components show first. */
export function studentNameParts(student: Named): { firstName: string; lastName: string } {
  if (student.first_name === null && student.last_name === null) {
    return { firstName: '', lastName: student.uid };
  }
  return { firstName: student.first_name ?? '', lastName: student.last_name ?? '' };
}
