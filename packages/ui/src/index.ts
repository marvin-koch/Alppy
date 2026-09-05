/**
 * @alppy/ui — the Encre violette design system.
 *
 * Styles are a separate entry point: `import '@alppy/ui/styles'` once in the
 * app, after the `@fontsource-variable` imports.
 *
 * The library ships NO translated strings and takes no i18n dependency: every
 * label, every accessible name and every number format arrives as a prop.
 */
export * from './components';
export * from './icons';
export * from './illustrations';
export * from './brand';
export { cx } from './lib/cx';
export type { ClassValue } from './lib/cx';
export { BAND_ORDER, BAND_THRESHOLDS, bandForScore } from './lib/mastery';
export type { MasteryBand, BandLabels } from './lib/mastery';
export type { CardTint, StatusVariant, MasteryValue } from './lib/types';
export { clamp, toPercent, pct } from './lib/geometry';
export { mergeRefs } from './lib/refs';
