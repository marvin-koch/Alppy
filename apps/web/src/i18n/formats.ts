import type { Formats } from 'next-intl';

/**
 * Shared format presets. Every date and number in the app goes through one of
 * these so `1'234.5` and `05.09.2026` never depend on the component.
 */
export const formats = {
  dateTime: {
    short: { day: '2-digit', month: '2-digit', year: 'numeric' },
    long: { day: 'numeric', month: 'long', year: 'numeric' },
    dayTime: { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' },
  },
  number: {
    percent: { style: 'percent', maximumFractionDigits: 0 },
    decimal: { maximumFractionDigits: 1 },
    integer: { maximumFractionDigits: 0 },
  },
} satisfies Formats;
