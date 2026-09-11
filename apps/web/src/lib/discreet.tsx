'use client';

/**
 * Projector mode: who can read the screen over the teacher's shoulder.
 *
 * Alppy's screens are projected. The class matrix goes up so the class can see
 * what the week looked like; the roster is left open while the room fills. Both
 * put every pupil's name on the wall next to a band that says how that child is
 * doing, and the product had nothing to say about it. It was careful in the
 * other direction — no name ever reaches a model provider (`alppy/ai/scrub.py`)
 * — and the audience that is actually in the room got no consideration at all.
 *
 * Two ideas, and the split matters:
 *
 *  · **`discreet`** is the persisted preference, a display switch like the
 *    others, applied as `data-discreet` before paint. It is the standing
 *    answer to "am I usually projecting?".
 *  · **reveal** is a deliberate, temporary, per-screen act. It lives in React
 *    state and nowhere else, so it cannot outlive the screen, cannot be
 *    restored by a reload, and cannot follow the teacher to the next lesson.
 *    A reveal that persisted would be a projector mode that quietly turns
 *    itself off, which is worse than not having one.
 *
 * What is hidden is identity, never data. A band beside `7B_04` is the same
 * band; the teacher reads their own class list to know who that is, and the
 * pupil two rows back does not. This is why the UID is the right fallback and a
 * blur or a redaction block would not be: the screen stays usable, and the
 * teacher loses nothing they were using it for.
 */

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

import { usePathname } from '@/i18n/navigation';

/** Reads the attribute `ThemeScript` has already applied. */
function readDiscreet(): boolean {
  if (typeof document === 'undefined') return false;
  return document.documentElement.getAttribute('data-discreet') === 'on';
}

const RevealContext = createContext<{
  revealed: boolean;
  setRevealed: (on: boolean) => void;
}>({ revealed: false, setRevealed: () => {} });

/**
 * Mounted once, in `Providers`, and reset on every navigation.
 *
 * One provider rather than one per screen, so no screen can forget to have
 * one and silently fall back to "not revealed" — but the reset on `pathname`
 * is what gives it per-screen semantics: revealing the roster and then walking
 * to the matrix arrives with names hidden again. Leaving is the commonest way
 * a teacher stops needing the reveal, and it should not be a thing they have
 * to remember to undo.
 */
export function RevealProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [revealed, setRevealed] = useState(false);

  useEffect(() => setRevealed(false), [pathname]);

  return (
    <RevealContext.Provider value={{ revealed, setRevealed }}>{children}</RevealContext.Provider>
  );
}

export interface Discretion {
  /** The standing preference. */
  discreet: boolean;
  /** Whether names are showing right now. */
  revealed: boolean;
  /** True when a name must be replaced by its UID. */
  hideNames: boolean;
  setRevealed: (on: boolean) => void;
}

export function useDiscretion(): Discretion {
  const [discreet, setDiscreet] = useState(false);
  const { revealed, setRevealed } = useContext(RevealContext);

  // After mount, and then whenever the attribute changes — the keyboard
  // shortcut and the settings screen both write it, and a screen that only
  // read it once would keep showing names after the teacher hit the shortcut,
  // which is the exact moment it must not.
  useEffect(() => {
    setDiscreet(readDiscreet());
    const observer = new MutationObserver(() => setDiscreet(readDiscreet()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-discreet'],
    });
    return () => observer.disconnect();
  }, []);

  return { discreet, revealed, hideNames: discreet && !revealed, setRevealed };
}

// The one pure decision lives on its own, so it can be imported without the
// context and the attribute observer that surround it here.
export { pupilLabel, type Pupil } from './pupil-label';
