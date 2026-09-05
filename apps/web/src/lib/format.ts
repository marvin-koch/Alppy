'use client';

import { useLocale } from 'next-intl';
import { useMemo } from 'react';
import { intlLocales, isAppLocale, type AppLocale } from '@/i18n/routing';

/**
 * Swiss number and date shapes. `fr` alone would print `1 234,5`; Suisse
 * romande writes `1'234.5`, and so does Deutschschweiz — hence `fr-CH` /
 * `de-CH`. Nothing in a component formats a number by hand.
 */
export interface Formatters {
  /** The BCP-47 tag actually used by `Intl`, e.g. `fr-CH`. */
  tag: string;
  /** 0..1 -> `84 %` (with the Swiss no-break space before the sign). */
  percent(value: number | null | undefined, fractionDigits?: number): string;
  /** A plain number: `1'234.5`. */
  number(value: number, fractionDigits?: number): string;
  integer(value: number): string;
  /** `16.03.2026` */
  date(value: string | Date | null | undefined): string;
  /** `16 mars 2026` */
  dateLong(value: string | Date | null | undefined): string;
  /** `16.03.2026, 14:30` */
  dateTime(value: string | Date | null | undefined): string;
  /** `il y a 4 jours` */
  relativeDays(value: string | Date | null | undefined, now?: Date): string;
  fileSize(bytes: number): string;
}

export function createFormatters(locale: AppLocale): Formatters {
  const tag = intlLocales[locale];
  const percentFormat = new Intl.NumberFormat(tag, { style: 'percent', maximumFractionDigits: 0 });
  const numberFormat = new Intl.NumberFormat(tag, { maximumFractionDigits: 1 });
  const integerFormat = new Intl.NumberFormat(tag, { maximumFractionDigits: 0 });
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
  const sizeFormat = new Intl.NumberFormat(tag, { maximumFractionDigits: 1 });

  const asDate = (value: string | Date | null | undefined): Date | null => {
    if (value === null || value === undefined) return null;
    const date = value instanceof Date ? value : new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  };

  return {
    tag,
    percent(value, fractionDigits) {
      if (value === null || value === undefined || Number.isNaN(value)) return '—';
      if (fractionDigits === undefined) return percentFormat.format(value);
      return new Intl.NumberFormat(tag, {
        style: 'percent',
        maximumFractionDigits: fractionDigits,
      }).format(value);
    },
    number(value, fractionDigits) {
      if (fractionDigits === undefined) return numberFormat.format(value);
      return new Intl.NumberFormat(tag, { maximumFractionDigits: fractionDigits }).format(value);
    },
    integer: (value) => integerFormat.format(value),
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
    fileSize: (bytes) => `${sizeFormat.format(bytes / 1_000_000)} MB`,
  };
}

export function useFormatters(): Formatters {
  const locale = useLocale();
  const appLocale: AppLocale = isAppLocale(locale) ? locale : 'fr';
  return useMemo(() => createFormatters(appLocale), [appLocale]);
}
