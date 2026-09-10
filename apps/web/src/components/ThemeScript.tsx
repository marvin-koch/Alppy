import { THEME_SCRIPT } from '@/lib/theme-script';

/**
 * Applies the four display switches before first paint.
 *
 * This has to be a blocking inline script. Setting the attributes in an effect
 * would paint the light palette first and then swap, which is the flash every
 * dark-mode implementation is judged by.
 *
 * `data-theme` absent is a real, third state — "follow the system" — and is not
 * a synonym for light. So the script only ever *sets* an attribute the teacher
 * has actually chosen, and removes it otherwise.
 *
 * The script text lives in `lib/theme-script` because `middleware.ts` allows it
 * through the CSP by hash and the two must not drift.
 */
export function ThemeScript() {
  return <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />;
}
