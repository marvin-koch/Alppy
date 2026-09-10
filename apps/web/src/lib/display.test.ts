import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  applyDisplay,
  defaultDisplay,
  DISPLAY_STORAGE_KEY,
  readDisplay,
  type DisplayPrefs,
} from './display';

/**
 * The four display switches. `null` is a real value here — "not chosen" means
 * follow the system — and the attribute must be *absent*, not set to a string,
 * or the CSS `:root:not([data-theme='light'])` guards stop working and a user
 * on the system default gets the wrong palette.
 */
describe('display preferences', () => {
  beforeEach(() => {
    window.localStorage.clear();
    for (const key of ['theme', 'contrast', 'motion', 'calm']) {
      document.documentElement.removeAttribute(`data-${key}`);
    }
  });

  it('reads the defaults when nothing is stored', () => {
    expect(readDisplay()).toEqual(defaultDisplay);
  });

  it('round-trips a full set of choices', () => {
    const prefs: DisplayPrefs = { theme: 'dark', contrast: 'high', motion: 'off', calm: 'on' };
    applyDisplay(prefs);
    expect(readDisplay()).toEqual(prefs);
  });

  it('writes an attribute for a choice and REMOVES it for "not chosen"', () => {
    applyDisplay({ theme: 'dark', contrast: 'high', motion: 'off', calm: 'on' });
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');

    applyDisplay(defaultDisplay);
    // Absent, not "null" — an attribute whose value is the string "null" still
    // matches [data-theme], which is how a system-default user gets stuck.
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(document.documentElement.hasAttribute('data-contrast')).toBe(false);
  });

  it('fills in missing keys from a partial stored object', () => {
    window.localStorage.setItem(DISPLAY_STORAGE_KEY, JSON.stringify({ theme: 'dark' }));
    expect(readDisplay()).toEqual({ ...defaultDisplay, theme: 'dark' });
  });

  it('falls back to the defaults on corrupt storage rather than throwing', () => {
    window.localStorage.setItem(DISPLAY_STORAGE_KEY, 'not json{');
    expect(readDisplay()).toEqual(defaultDisplay);
  });

  it('survives storage being unavailable — a private window is not an error', () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    try {
      expect(readDisplay()).toEqual(defaultDisplay);
      // Storage is a convenience; the attributes are what actually theme the
      // page, so they must still be applied.
      expect(() => applyDisplay({ ...defaultDisplay, theme: 'dark' })).not.toThrow();
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });
});
