import { describe, expect, it } from 'vitest';

import { studentName, studentNameParts, studentSortName } from './studentName';

const lea = { uid: '7B_01', first_name: 'Léa', last_name: 'Roth' };
const anonymised = { uid: '7B_15', first_name: null, last_name: null };

describe('a pupil with a name', () => {
  it('reads as written, and sorts by surname', () => {
    expect(studentName(lea)).toBe('Léa Roth');
    expect(studentSortName(lea)).toBe('ROTH Léa');
    expect(studentNameParts(lea)).toEqual({ firstName: 'Léa', lastName: 'Roth' });
  });
});

describe('an anonymised pupil', () => {
  it('falls back to the uid, never to a blank', () => {
    // A blank row looks like a rendering bug. The uid is retained precisely
    // because it is what the printed sheet carries.
    expect(studentName(anonymised)).toBe('7B_15');
    expect(studentSortName(anonymised)).toBe('7B_15');
    expect(studentNameParts(anonymised)).toEqual({ firstName: '', lastName: '7B_15' });
  });

  it('is not confused with a pupil who has only one name recorded', () => {
    const partial = { uid: '7B_02', first_name: 'Noah', last_name: null };
    expect(studentName(partial)).toBe('Noah');
    expect(studentNameParts(partial)).toEqual({ firstName: 'Noah', lastName: '' });
  });
});
