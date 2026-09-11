'use client';

import { useLocale } from 'next-intl';
import { useMemo } from 'react';
import { intlLocales, isAppLocale, type AppLocale } from '@/i18n/routing';

/**
 * Swiss number and date shapes. Nothing in a component formats a number by hand.
 *
 * The locale tag is NOT what makes a number Swiss, and believing it was is how
 * this file came to describe behaviour it never had. CLDR's `fr-CH` is identical
 * to plain `fr` — `1 234,5` — and only `de-CH` and `en-CH` carry the apostrophe
 * group and the period decimal. The comment here used to claim `fr-CH` printed
 * `1'234.5`; it never did, and audit 05 §10.1 repeated the error and dismissed
 * the brief's §54 on the strength of it.
 *
 * So the two marks are substituted explicitly, in every locale, by `swissify`
 * below. Everything else stays where CLDR put it.
 */
export interface Formatters {
  /** The BCP-47 tag actually used by `Intl`, e.g. `fr-CH`. */
  tag: string;
  /** 0..1 -> `84 %` (with the Swiss no-break space before the sign). */
  percent(value: number | null | undefined, fractionDigits?: number): string;
  /** A plain number: `1’234.5`, in every locale. */
  number(value: number, fractionDigits?: number): string;
  integer(value: number): string;
  /** `16.03.2026` */
  date(value: string | Date | null | undefined): string;
  /** `16 mars 2026` */
  dateLong(value: string | Date | null | undefined): string;
  /** `16.03.2026 14:30` in `fr`; `de`/`en` put a comma after the date. */
  dateTime(value: string | Date | null | undefined): string;
  /** `il y a 4 jours` */
  relativeDays(value: string | Date | null | undefined, now?: Date): string;
  fileSize(bytes: number): string;
}

/**
 * The Swiss group and decimal marks: `1’234.5`, in French too.
 *
 * U+2019, not an ASCII apostrophe — that is the character CLDR gives `de-CH`,
 * so German and English are unchanged by this and French now agrees with them.
 * Pinned rather than read off `de-CH` so an ICU upgrade cannot quietly move the
 * French UI on its own.
 *
 * A deliberate departure from CLDR for `fr` (D101): Suisse romande prose really
 * does write a comma, but a barème, a points total and a class average are
 * figures on a school document, and `1’234.5` is what a teacher reads there.
 */
const GROUP_MARK = '\u2019';
const DECIMAL_MARK = '.';

/**
 * One locale's formatter, with the two marks replaced.
 *
 * Through `formatToParts` rather than a string replace, so it cannot touch a
 * digit, the no-break space before `%`, or a minus sign — only the parts ICU
 * itself labelled `group` and `decimal`.
 */
function swissify(format: Intl.NumberFormat): (value: number) => string {
  return (value) =>
    format
      .formatToParts(value)
      .map((part) =>
        part.type === 'group' ? GROUP_MARK : part.type === 'decimal' ? DECIMAL_MARK : part.value,
      )
      .join('');
}

export function createFormatters(locale: AppLocale): Formatters {
  const tag = intlLocales[locale];
  const percentFormat = swissify(
    new Intl.NumberFormat(tag, { style: 'percent', maximumFractionDigits: 0 }),
  );
  const numberFormat = swissify(new Intl.NumberFormat(tag, { maximumFractionDigits: 1 }));
  const integerFormat = swissify(new Intl.NumberFormat(tag, { maximumFractionDigits: 0 }));
  const dateFormat = new Intl.DateTimeFormat(tag, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'Europe/Zurich',
  });
  const dateLongFormat = new Intl.DateTimeFormat(tag, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'Europe/Zurich',
  });
  const dateTimeFormat = new Intl.DateTimeFormat(tag, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Zurich',
  });
  const relativeFormat = new Intl.RelativeTimeFormat(tag, { numeric: 'auto' });
  const sizeFormat = swissify(new Intl.NumberFormat(tag, { maximumFractionDigits: 1 }));

  const asDate = (value: string | Date | null | undefined): Date | null => {
    if (value === null || value === undefined) return null;
    const date = value instanceof Date ? value : new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  };

  return {
    tag,
    percent(value, fractionDigits) {
      if (value === null || value === undefined || Number.isNaN(value)) return '—';
      if (fractionDigits === undefined) return percentFormat(value);
      return swissify(
        new Intl.NumberFormat(tag, {
          style: 'percent',
          maximumFractionDigits: fractionDigits,
        }),
      )(value);
    },
    number(value, fractionDigits) {
      if (fractionDigits === undefined) return numberFormat(value);
      return swissify(new Intl.NumberFormat(tag, { maximumFractionDigits: fractionDigits }))(value);
    },
    integer: (value) => integerFormat(value),
    date: (value) => {
      const date = asDate(value);
      return date ? dateFormat.format(date) : '—';
    },
    dateLong: (value) => {
      const date = asDate(value);
      return date ? dateLongFormat.format(date) : '—';
    },
    dateTime: (value) => {
      const date = asDate(value);
      return date ? dateTimeFormat.format(date) : '—';
    },
    relativeDays: (value, now = new Date()) => {
      const date = asDate(value);
      if (!date) return '—';
      const days = Math.round((date.getTime() - now.getTime()) / 86_400_000);
      return relativeFormat.format(days, 'day');
    },
    fileSize: (bytes) => `${sizeFormat(bytes / 1_000_000)} MB`,
  };
}

export function useFormatters(): Formatters {
  const locale = useLocale();
  const appLocale: AppLocale = isAppLocale(locale) ? locale : 'fr';
  return useMemo(() => createFormatters(appLocale), [appLocale]);
}
