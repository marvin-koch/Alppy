import { useCallback, useRef } from 'react';

/**
 * Return focus to whatever opened an overlay.
 *
 * Radix only restores focus to a `Dialog.Trigger`. When the app drives `open`
 * itself — the common case here, e.g. the AppShell drawer — `triggerRef` is
 * null, and Radix's own `onCloseAutoFocus` still calls `preventDefault()`,
 * which cancels the FocusScope fallback too. Focus then lands on `<body>` and
 * a keyboard user is dropped back at the top of the document.
 *
 * So we remember the opener ourselves. `onOpenAutoFocus` is dispatched by
 * FocusScope *before* it moves focus into the overlay, so `document.activeElement`
 * at that moment is still the element the user acted on.
 *
 * Returns handlers to spread onto a Radix content element. When there is no
 * usable opener we leave the event alone and let Radix behave as it does today.
 */
export function useReturnFocus(): {
  onOpenAutoFocus: (event: Event) => void;
  onCloseAutoFocus: (event: Event) => void;
} {
  const openerRef = useRef<HTMLElement | null>(null);

  const onOpenAutoFocus = useCallback((_event: Event) => {
    const active = document.activeElement;
    openerRef.current = active instanceof HTMLElement && active !== document.body ? active : null;
  }, []);

  const onCloseAutoFocus = useCallback((event: Event) => {
    const opener = openerRef.current;
    openerRef.current = null;
    // Gone from the DOM (a route change, a list item that was deleted): let
    // Radix decide rather than focusing a detached node.
    if (opener === null || !opener.isConnected) return;
    event.preventDefault();
    opener.focus();
  }, []);

  return { onOpenAutoFocus, onCloseAutoFocus };
}
