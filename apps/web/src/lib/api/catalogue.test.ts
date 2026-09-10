import de from '../../../messages/de.json';
import en from '../../../messages/en.json';
import fr from '../../../messages/fr.json';
import { describe, expect, it } from 'vitest';

/**
 * `pnpm i18n:check` proves the three catalogues agree with each other. It
 * cannot prove a key that code depends on exists in any of them — and
 * `apiErrorMessage` reaches for `errors.code.fallback` on every unrecognised
 * failure, which is exactly when nothing else is going to save the screen.
 */
describe.each([
  ['fr', fr],
  ['de', de],
  ['en', en],
])('%s catalogue', (_locale, messages) => {
  it('has the error-code fallback every failed request lands on', () => {
    expect(messages.errors.code.fallback).toBeTruthy();
  });

  it('has a sentence for a sheet the renderer refuses', () => {
    expect(messages.errors.code.sheet_not_renderable).toBeTruthy();
  });
});
