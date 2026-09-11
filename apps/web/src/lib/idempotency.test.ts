/**
 * The key belongs to the intent, not to the request.
 *
 * These are the two assertions that matter, and they are opposites: a retry of
 * the same intention MUST reuse the key (otherwise the server does the work
 * twice, which is what `Idempotency-Key` exists to prevent), and a genuinely new
 * intention MUST NOT (otherwise the server replies with the previous result,
 * which is worse). A key minted per request satisfies the second and fails the
 * first, and looks completely fine in a screenshot.
 */

import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useIdempotencyKey } from './idempotency';

describe('an idempotent intent', () => {
  it('returns the same key for every attempt at one intent', () => {
    const { result } = renderHook(() => useIdempotencyKey());

    const first = result.current.key();
    const retry = result.current.key();
    const again = result.current.key();

    expect(retry).toBe(first);
    expect(again).toBe(first);
  });

  it('mints a fresh key once the intent has completed', () => {
    const { result } = renderHook(() => useIdempotencyKey());

    const first = result.current.key();
    result.current.clear();
    const second = result.current.key();

    expect(second).not.toBe(first);
  });

  /** The file-selection case: the teacher chose different photographs, so the
   *  previous key must not be reused even though nothing succeeded. */
  it('mints a fresh key when a new intent is armed mid-flight', () => {
    const { result } = renderHook(() => useIdempotencyKey());

    const first = result.current.key();
    const restarted = result.current.restart();

    expect(restarted).not.toBe(first);
    // And the restarted key is now the one a retry reuses.
    expect(result.current.key()).toBe(restarted);
  });

  it('survives a re-render, because a ref is not state', () => {
    const { result, rerender } = renderHook(() => useIdempotencyKey());

    const first = result.current.key();
    rerender();
    rerender();

    expect(result.current.key()).toBe(first);
  });

  it('gives two separate intents two separate keys', () => {
    const a = renderHook(() => useIdempotencyKey());
    const b = renderHook(() => useIdempotencyKey());

    expect(a.result.current.key()).not.toBe(b.result.current.key());
  });
});
