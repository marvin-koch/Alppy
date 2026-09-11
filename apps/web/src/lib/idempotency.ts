'use client';

import { useCallback, useRef } from 'react';

/**
 * One key per teacher INTENT, reused across every retry of that intent.
 *
 * This is the whole mechanism, and it is easy to build backwards. A key minted
 * per REQUEST is a different key on the retry, so the server treats the retry as
 * new work and does it twice — which is the exact case `Idempotency-Key` exists
 * to collapse (D98, `services/idempotency.py`). So the key is armed when the
 * teacher forms the intention — a file selection, the first press of the button —
 * held in a ref across however many attempts that intention takes, and released
 * only when the work actually succeeded.
 *
 * A ref rather than state: nothing renders differently because of it, and a
 * `setState` here would re-render a screen mid-upload for no visible reason.
 *
 * The four routes it guards are the ones that cost real money or real paper:
 * uploading a pile of photographs, rendering a sheet to PDF, building a
 * differentiation batch (one provider call per pupil) and rendering that batch.
 */
export interface IdempotentIntent {
  /**
   * The key for the intent in progress, minting one if none is armed.
   *
   * Calling it twice for the same intent — a retry — returns the same string.
   */
  key: () => string;
  /**
   * Arm a NEW intent, discarding any key in flight.
   *
   * For the case a retry must not cover: the teacher chose different files, or
   * pressed the button again having changed something. Repeating the previous key
   * there would have the server answer with the PREVIOUS result, which is worse
   * than doing the work twice.
   */
  restart: () => string;
  /** The intent completed. The next `key()` mints a fresh one. */
  clear: () => void;
}

/**
 * A UUID, from the platform where it has one.
 *
 * `crypto.randomUUID` needs a secure context, and a teacher may reach a dev or
 * on-premises deployment over plain http. The fallback is not cryptographic and
 * does not need to be: this value only has to be unique among one browser's own
 * in-flight requests, and the server treats it as an opaque string.
 */
function mint(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function useIdempotencyKey(): IdempotentIntent {
  const current = useRef<string | null>(null);

  const key = useCallback(() => {
    current.current ??= mint();
    return current.current;
  }, []);

  const restart = useCallback(() => {
    current.current = mint();
    return current.current;
  }, []);

  const clear = useCallback(() => {
    current.current = null;
  }, []);

  return { key, restart, clear };
}
