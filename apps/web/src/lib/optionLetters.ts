/**
 * The glyphs printed beside an answer bubble.
 *
 * Mirrors `OptionLetters` and `tf_letters` in
 * `apps/api/alppy/sheets/layout.py`, layout version v1. The positions never
 * move — only the glyph does — which is what lets the scan detector read a
 * page without knowing its language.
 *
 * The web previews used to hardcode `'ABCD'` for every item type, so a
 * true/false item showed A/B on screen and printed V/F on paper. A preview
 * that disagrees with the paper is worse than no preview.
 */
import { SHEET_LAYOUT } from '@alppy/shared';

export const MCQ_LETTERS = 'ABCD';

/** How many bubbles one item can claim, straight from `layout.py`. */
export const MAX_OPTIONS = SHEET_LAYOUT.grid.maxOptions;

/** How many items fit the fixed answer grid on one physical page. */
export const ITEMS_PER_PAGE = SHEET_LAYOUT.itemsPerPage;

const TRUE_FALSE_LETTERS: Record<string, string> = {
  fr: 'VF', // Vrai / Faux
  de: 'RF', // Richtig / Falsch
  en: 'TF', // True / False
};

export function trueFalseLetters(language: string | null | undefined): string {
  return TRUE_FALSE_LETTERS[language ?? ''] ?? TRUE_FALSE_LETTERS.en!;
}

export function optionLetters(
  type: string | null | undefined,
  language: string | null | undefined,
): string {
  if (type === 'true_false') return trueFalseLetters(language);
  if (type === 'mcq') return MCQ_LETTERS;
  return '';
}
