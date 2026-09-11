/**
 * Every date, number, percentage and file size in the product comes from here,
 * and until now none of it was tested (audit 05 G32).
 *
 * The separator assertions are the load-bearing ones, because the belief they
 * replace was written down in three places and was wrong in all of them:
 * `format.ts`'s own comment, and audit 05 §10.1, both claimed CLDR's `fr-CH`
 * prints `1'234.5`. It does not — `fr-CH` is byte-identical to plain `fr` and
 * prints `1 234,5`. Only `de-CH` and `en-CH` carry the apostrophe and the
 * period. So the marks are now substituted explicitly, and these tests are what
 * stop someone restoring the locale-tag version on the strength of the same
 * wrong belief.
 */

import { describe, expect, it } from 'vitest';

import { createFormatters } from './format';

const LOCALES = ['fr', 'de', 'en'] as const;

describe('the Swiss marks', () => {
  /** U+2019, the character CLDR itself gives `de-CH` — not an ASCII apostrophe. */
  const GROUP = '’';

  it.each(LOCALES)('groups with U+2019 and decimalises with a period in %s', (locale) => {
    const fmt = createFormatters(locale);
    expect(fmt.number(1234.5)).toBe(`1${GROUP}234.5`);
    expect(fmt.number(0.25, 2)).toBe('0.25');
    expect(fmt.integer(12345)).toBe(`12${GROUP}345`);
  });

  /** The whole point: all three agree. A teacher switching the UI language does
   *  not see the same barème punctuated two ways. */
  it('formats a number identically in all three locales', () => {
    const rendered = LOCALES.map((l) => createFormatters(l).number(1234.5));
    expect(new Set(rendered).size).toBe(1);
  });

  it('never emits a comma as a decimal mark', () => {
    for (const locale of LOCALES) {
      const fmt = createFormatters(locale);
      for (const value of [0.5, 0.25, 1.5, 1234.5, -2.75]) {
        expect(fmt.number(value, 2)).not.toMatch(/\d,\d/);
      }
    }
  });

  /** Substituted through `formatToParts`, so a minus sign and the digits are
   *  the locale's own and only the two marks are ours. */
  it('leaves a negative number negative', () => {
    expect(createFormatters('fr').number(-1234.5)).toBe(`-1${GROUP}234.5`);
  });
});

describe('percentages', () => {
  it('renders a ratio as a whole percentage', () => {
    expect(createFormatters('fr').percent(0.84)).toContain('84');
    expect(createFormatters('fr').percent(0.84)).toContain('%');
  });

  /** The rule the whole points module exists for: nothing graded is not zero. */
  it.each([null, undefined, Number.NaN])('renders %s as an em dash, never 0 %%', (value) => {
    expect(createFormatters('fr').percent(value as number | null | undefined)).toBe('—');
  });

  it('honours a requested precision', () => {
    expect(createFormatters('fr').percent(0.8425, 1)).toContain('84.3');
  });
});

describe('dates', () => {
  const AT = '2026-03-16T13:30:00Z';

  it('writes a short date the Swiss way, zero-padded', () => {
    expect(createFormatters('fr').date(AT)).toBe('16.03.2026');
    expect(createFormatters('de').date(AT)).toBe('16.03.2026');
  });

  it('names the month in the UI language', () => {
    expect(createFormatters('fr').dateLong(AT)).toBe('16 mars 2026');
    expect(createFormatters('de').dateLong(AT)).toContain('März');
  });

  /** Europe/Zurich, not the viewer's zone: a sheet printed at 00:30 CET must not
   *  be filed under the previous day for a teacher whose laptop is on UTC. 13:30
   *  UTC is 14:30 in Zurich, and reading it as UTC would print 13:30. */
  it('reads times in Europe/Zurich', () => {
    // No comma after the date in `fr-CH`; `de`/`en` add one. That difference is
    // CLDR's and is left alone — only the NUMBER marks are overridden here.
    expect(createFormatters('fr').dateTime(AT)).toBe('16.03.2026 14:30');
    expect(createFormatters('de').dateTime(AT)).toBe('16.03.2026, 14:30');
  });

  it.each([null, undefined, 'not a date'])('renders %s as an em dash', (value) => {
    const fmt = createFormatters('fr');
    expect(fmt.date(value)).toBe('—');
    expect(fmt.dateLong(value)).toBe('—');
    expect(fmt.dateTime(value)).toBe('—');
    expect(fmt.relativeDays(value)).toBe('—');
  });

  it('counts relative days from a given now', () => {
    const now = new Date('2026-03-20T12:00:00Z');
    expect(createFormatters('fr').relativeDays('2026-03-16T12:00:00Z', now)).toMatch(/4/);
    expect(createFormatters('fr').relativeDays('2026-03-19T12:00:00Z', now)).toMatch(/hier/i);
  });
});

describe('file sizes', () => {
  it('reports megabytes with the Swiss decimal mark', () => {
    expect(createFormatters('fr').fileSize(2_500_000)).toBe('2.5 MB');
  });

  it('is the same string in every locale', () => {
    const rendered = LOCALES.map((l) => createFormatters(l).fileSize(2_500_000));
    expect(new Set(rendered).size).toBe(1);
  });
});

describe('the tag', () => {
  it('reports the BCP-47 tag actually used', () => {
    expect(createFormatters('fr').tag).toBe('fr-CH');
    expect(createFormatters('de').tag).toBe('de-CH');
  });
});
