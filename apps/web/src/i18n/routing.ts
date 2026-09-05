import { defineRouting } from 'next-intl/routing';

/**
 * French is the default: Alppy is built for Suisse romande first, and the
 * teacher's choice is persisted server-side (`TeacherPreferences.locale`).
 * The locale always appears in the path so a link is unambiguous.
 */
export const locales = ['fr', 'de', 'en'] as const;

export type AppLocale = (typeof locales)[number];

export const defaultLocale: AppLocale = 'fr';

/**
 * Swiss formatting: `1'234.5`. `fr-CH` and `de-CH` both use the apostrophe
 * group separator; a plain `fr` would print `1 234,5`, which is wrong here.
 */
export const intlLocales: Record<AppLocale, string> = {
  fr: 'fr-CH',
  de: 'de-CH',
  en: 'en-CH',
};

export const routing = defineRouting({
  locales,
  defaultLocale,
  localePrefix: 'always',
  localeDetection: true,
});

export function isAppLocale(value: string): value is AppLocale {
  return (locales as readonly string[]).includes(value);
}
