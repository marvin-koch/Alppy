import { getRequestConfig } from 'next-intl/server';
import { formats } from './formats';
import { defaultLocale, isAppLocale } from './routing';

/**
 * The routing locale stays `fr` / `de` / `en` — it is the path segment. Swiss
 * number and date shapes (`1'234.5`) come from `src/lib/format.ts`, which maps
 * the routing locale onto `fr-CH` / `de-CH` / `en-CH`.
 */
export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = requested && isAppLocale(requested) ? requested : defaultLocale;

  return {
    locale,
    formats,
    timeZone: 'Europe/Zurich',
    messages: (await import(`../../messages/${locale}.json`)).default,
    getMessageFallback({ key }) {
      /* A missing key must never blank a screen. */
      return key;
    },
  };
});
