'use client';

/**
 * Whether Alppy can currently be reached (F24).
 *
 * The product is used on a phone in a classroom, which is the worst wifi in the
 * building, and nothing anywhere told a teacher that the reason a verdict would
 * not save was the connection. Every failure read the same as every other:
 * "L'envoi a échoué. Réessayez."
 *
 * Two signals, and the order matters:
 *
 *  · `navigator.onLine` is cheap and immediate, and answers the weaker
 *    question — does this machine think it has a network. A school wifi that
 *    associates but routes nowhere says `true` the whole time.
 *  · The last request's own outcome answers the real one. `api/client.ts`
 *    reports it; a `network_error` means the fetch never got an answer, and
 *    anything the server said — including a 500 — proves it is there.
 *
 * So the bar appears when EITHER says we are cut off, and clears only when a
 * request actually succeeds. Being told "no" is not being unable to ask.
 */

import { useEffect, useState } from 'react';

import { onApiReachability } from './api/client';

export interface ConnectionState {
  /** The browser's own view. False is reliable; true is only a hint. */
  online: boolean;
  /** Did the last request reach the API. Starts optimistic: nothing has failed. */
  reachable: boolean;
}

export function useConnection(): ConnectionState {
  // Optimistic on the server and on the first paint: a bar that flashes
  // "hors ligne" on every load would train a teacher to ignore it.
  const [online, setOnline] = useState(true);
  const [reachable, setReachable] = useState(true);

  useEffect(() => {
    setOnline(navigator.onLine);
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener('online', goOnline);
    window.addEventListener('offline', goOffline);
    const stop = onApiReachability(setReachable);
    return () => {
      window.removeEventListener('online', goOnline);
      window.removeEventListener('offline', goOffline);
      stop();
    };
  }, []);

  return { online, reachable };
}
