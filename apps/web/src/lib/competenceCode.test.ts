import { describe, expect, it } from 'vitest';

import { competenceCodes } from './competenceCode';

const row = (competency_id: string, code: string, edition: string | null) => ({
  competency_id,
  code,
  edition,
});

describe('competenceCodes', () => {
  it('leaves an unambiguous code alone', () => {
    const codes = competenceCodes([row('a', 'MSN 32', '2023'), row('b', 'MSN 33', '2023')]);
    expect(codes.get('a')).toBe('MSN 32');
    expect(codes.get('b')).toBe('MSN 33');
  });

  it('names the edition when one code appears twice', () => {
    // The demo database's real shape: a school part-way through a migration,
    // with Themes hanging off both revisions of MSN 34.
    const codes = competenceCodes([
      row('a', 'MSN 32', '2023'),
      row('b', 'MSN 34', '2023'),
      row('c', 'MSN 34', '2010'),
    ]);
    expect(codes.get('a')).toBe('MSN 32');
    expect(codes.get('b')).toBe('MSN 34 (2023)');
    expect(codes.get('c')).toBe('MSN 34 (2010)');
  });

  it('falls back to the bare code when the edition is unknown', () => {
    const codes = competenceCodes([row('a', 'MSN 34', null), row('b', 'MSN 34', null)]);
    expect(codes.get('a')).toBe('MSN 34');
    expect(codes.get('b')).toBe('MSN 34');
  });
});
