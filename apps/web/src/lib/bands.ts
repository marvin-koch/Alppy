'use client';

import type { BandLabels, MasteryBand } from '@alppy/ui';
import { useTranslations } from 'next-intl';

/**
 * `@alppy/ui` ships no translated strings by design, so the app supplies every
 * band label. Colour is never the only channel: these words are the second one.
 */
export function useBandLabels(): BandLabels {
  const t = useTranslations('mastery.band');
  return {
    solid: t('solid'),
    ok: t('ok'),
    weak: t('weak'),
    fading: t('fading'),
    none: t('none'),
  };
}

/**
 * The threshold behind each band, for the legend. These strings shipped in all
 * three catalogues and were referenced by nothing, so the legend named five
 * bands without ever saying what they mean.
 */
export function useBandHelp(): Record<MasteryBand, string> {
  const t = useTranslations('mastery.bandHelp');
  return {
    solid: t('solid'),
    ok: t('ok'),
    weak: t('weak'),
    fading: t('fading'),
    none: t('none'),
  };
}

export const BAND_KEYS: MasteryBand[] = ['solid', 'ok', 'weak', 'fading', 'none'];
