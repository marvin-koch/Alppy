/**
 * Projector mode's one pure decision: what a pupil is called on screen.
 *
 * The rest of the mode is wiring — an attribute, a context, a reveal that
 * resets on navigation — and the e2e suite drives that. This is the part with
 * a right answer.
 */

import { describe, expect, it } from 'vitest';

import { pupilLabel } from './pupil-label';

const pupil = { uid: '7B_04', first_name: 'Léa', last_name: 'Berthod' };

describe('pupilLabel', () => {
  it('names the pupil when nothing is being hidden', () => {
    expect(pupilLabel(pupil, false)).toBe('Léa Berthod');
  });

  /**
   * The UID rather than initials, a blur or a redaction block: it is the code
   * already printed on that child's own paper, so the teacher can resolve it
   * from the pile in their hand, and it is meaningless to the rest of the room.
   * The screen stays as usable as it was.
   */
  it('falls back to the code that is on the pupil’s own paper', () => {
    expect(pupilLabel(pupil, true)).toBe('7B_04');
  });

  /** Hiding must never produce an empty cell: a row with no label at all is a
   *  row a teacher cannot act on, which is a worse screen, not a safer one. */
  it('never renders nothing', () => {
    expect(pupilLabel({ uid: '7B_09', first_name: '', last_name: '' }, true)).toBe('7B_09');
    expect(pupilLabel({ uid: '7B_09', first_name: 'Ana', last_name: '' }, false)).toBe('Ana');
  });
});
