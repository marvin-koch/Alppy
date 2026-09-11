'use client';

/**
 * The display switches (DESIGN.md §8), persisted in two places on purpose:
 * server-side on the teacher record so the choice follows them to another
 * machine, and in localStorage so `ThemeScript` can apply it before paint
 * without waiting for a request.
 */
export type ThemeChoice = 'light' | 'dark' | null;

export interface DisplayPrefs {
  theme: ThemeChoice;
  contrast: 'high' | null;
  motion: 'off' | null;
  calm: 'on' | null;
  /**
   * Projector mode. Names collapse to UIDs wherever pupils are listed, and the
   * teacher reveals them deliberately.
   *
   * A display switch rather than a screen-level option because that is what it
   * is: the data does not change, only who can read it over the teacher's
   * shoulder. It rides the same `data-*` attribute, so the moment it is set it
   * is set for every screen at once — which matters, because the realistic
   * trigger is realising you need it while the projector is already on.
   */
  discreet: 'on' | null;
}

export const DISPLAY_STORAGE_KEY = 'alppy.display';

export const defaultDisplay: DisplayPrefs = {
  theme: null,
  contrast: null,
  motion: null,
  calm: null,
  discreet: null,
};

export function readDisplay(): DisplayPrefs {
  if (typeof window === 'undefined') return defaultDisplay;
  try {
    const raw = window.localStorage.getItem(DISPLAY_STORAGE_KEY);
    if (!raw) return defaultDisplay;
    return { ...defaultDisplay, ...(JSON.parse(raw) as Partial<DisplayPrefs>) };
  } catch {
    // A private window, or storage disabled. The defaults are correct.
    return defaultDisplay;
  }
}

/** Writes the attributes and mirrors them to storage. Absent means "not chosen". */
export function applyDisplay(prefs: DisplayPrefs): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  (['theme', 'contrast', 'motion', 'calm', 'discreet'] as const).forEach((key) => {
    const value = prefs[key];
    if (value) root.setAttribute(`data-${key}`, value);
    else root.removeAttribute(`data-${key}`);
  });
  try {
    window.localStorage.setItem(DISPLAY_STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    /* storage is a convenience here, never the source of truth */
  }
}
