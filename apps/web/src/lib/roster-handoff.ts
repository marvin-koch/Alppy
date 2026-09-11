'use client';

/**
 * A pasted roster, carried from the create-class screen to the roster screen.
 *
 * Creating a class is two sequential writes: `POST /classes`, then
 * `POST /classes/{id}/students`. If the second failed, the class existed, the
 * teacher was left on the create form holding the only copy of a pasted roster,
 * and resubmitting hit a 409 on the class code — so the remedy for a half-finished
 * create was to lose the list and start again (G16). The class is created either
 * way, so the honest move is to go where the roster can be retried: the roster
 * screen already handles a failed post correctly, because there the class exists.
 *
 * NOT a query parameter, and that is the point of this module. A roster is twenty
 * children's full names, and putting those in a URL means browser history, server
 * logs, the Referer header and a link a teacher might paste to a colleague. The
 * pupil's identifier was deliberately taken out of the URL for the same reason.
 *
 * `sessionStorage` rather than `localStorage`: it belongs to this tab and this
 * session, and it is cleared as soon as it is read, so a roster cannot outlive the
 * handoff it exists for.
 */

const KEY = 'alppy.rosterHandoff';

/** Park the pasted text for the roster screen to pick up. */
export function stashRoster(classId: string, text: string): void {
  if (typeof window === 'undefined' || text.trim() === '') return;
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify({ classId, text }));
  } catch {
    // A private window, or storage blocked. The teacher retypes; nothing breaks.
  }
}

/**
 * Take it, once, for this class.
 *
 * Keyed on the class so a handoff for one class cannot surface on another's roster
 * screen, and removed on read so a reload does not resurrect a list the teacher
 * has already dealt with.
 */
export function takeRoster(classId: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { classId?: string; text?: string };
    if (parsed.classId !== classId || !parsed.text) return null;
    window.sessionStorage.removeItem(KEY);
    return parsed.text;
  } catch {
    return null;
  }
}
