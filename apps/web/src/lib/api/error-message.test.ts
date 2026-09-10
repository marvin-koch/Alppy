import { describe, expect, it } from 'vitest';

import { ApiError } from './client';
import { apiErrorMessage } from './error-message';

/** A stand-in for next-intl's `t`, which throws on a key it does not have. */
function catalogue(entries: Record<string, string>) {
  return (key: string): string => {
    const value = entries[key];
    if (value === undefined) throw new Error(`MISSING_MESSAGE: ${key}`);
    return value;
  };
}

const FULL = catalogue({
  fallback: 'Something failed. Try again.',
  sheet_not_renderable: 'This sheet cannot be laid out as it stands.',
});

describe('apiErrorMessage', () => {
  it('localises a known code', () => {
    const error = new ApiError(422, 'sheet_not_renderable', 'no students in class 7B');
    expect(apiErrorMessage(error, FULL)).toBe('This sheet cannot be laid out as it stands.');
  });

  /** The whole reason this function exists: the API's `message` is for the
   *  console, and a French teacher must never read it. */
  it('never returns the API message', () => {
    const error = new ApiError(422, 'sheet_not_renderable', 'no students in class 7B');
    expect(apiErrorMessage(error, FULL)).not.toContain('7B');
  });

  it('falls back on an unrecognised code', () => {
    const error = new ApiError(500, 'some_new_code', 'internal');
    expect(apiErrorMessage(error, FULL)).toBe('Something failed. Try again.');
  });

  it('falls back on a non-ApiError', () => {
    expect(apiErrorMessage(new TypeError('boom'), FULL)).toBe('Something failed. Try again.');
    expect(apiErrorMessage(undefined, FULL)).toBe('Something failed. Try again.');
  });

  /**
   * The regression that mattered. Five call sites passed the `errors`
   * namespace instead of `errors.code`, so the code lookup missed AND the
   * fallback lookup missed — and the second throw escaped, crashing a screen
   * that was in the middle of reporting a handled failure.
   */
  it('does not throw when even the fallback key is missing', () => {
    const empty = catalogue({});
    expect(() => apiErrorMessage(new ApiError(500, 'x', 'y'), empty)).not.toThrow();
    expect(apiErrorMessage(new ApiError(500, 'x', 'y'), empty)).toBe('');
  });
});
