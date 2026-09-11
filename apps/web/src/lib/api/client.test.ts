/**
 * What happens when the session dies mid-review.
 *
 * This is the test for F5, and it is really a test that a *second* thing now
 * happens on a 401. The first — declining to retry — has been in `Providers`
 * since F7 and is correct; it just leaves the teacher on a screen that looks
 * like it is working, pressing verdicts into an API that answers 401 to every
 * one of them.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiRequest, setUnauthorizedHandler } from './client';

/** A response the way `parseError` expects to find it. */
function respond(status: number, body: unknown = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const expired = {
  error: { code: 'unauthorized', message: 'authentication required', details: {}, request_id: null },
};

describe('a 401 from the API', () => {
  let handler: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    handler = vi.fn();
    setUnauthorizedHandler(handler);
  });

  afterEach(() => {
    setUnauthorizedHandler(null);
    vi.unstubAllGlobals();
  });

  it('reaches the handler that clears the cache and redirects', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(401, expired)));

    await expect(apiRequest('/scans/abc/detections/def')).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  /** The predicate that had zero callers for five days is the one deciding. */
  it('is recognised by the predicate rather than by a magic number', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(401, expired)));

    const error = await apiRequest('/home').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).isUnauthorized).toBe(true);
  });

  /**
   * `/auth/me` is the app asking whether there is a session at all. A 401 is
   * that question's answer — the signed-out state, which the middleware
   * already handles — and redirecting on it would send the login screen to
   * itself in a loop.
   */
  it('does not fire on the session probe', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(401, expired)));

    await expect(apiRequest('/auth/me')).rejects.toBeInstanceOf(ApiError);
    expect(handler).not.toHaveBeenCalled();
  });

  /** Nor on a rejected sign-in: that is bad credentials, and the login screen
   *  owns the sentence for it (F15). */
  it('does not fire on a failed login', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(401, expired)));

    await expect(apiRequest('/auth/login', { method: 'POST' })).rejects.toBeInstanceOf(ApiError);
    expect(handler).not.toHaveBeenCalled();
  });

  it('leaves every other failure alone', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        respond(422, { error: { code: 'validation_error', message: 'no', details: {} } }),
      ),
    );

    await expect(apiRequest('/sheets')).rejects.toBeInstanceOf(ApiError);
    expect(handler).not.toHaveBeenCalled();
  });

  /** The API being unreachable is not the session being gone, and telling a
   *  teacher to sign in again when the server is down sends them to a login
   *  screen that cannot work either. */
  it('leaves an unreachable API alone', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('failed to fetch')));

    const error = await apiRequest('/home').catch((e: unknown) => e);
    expect((error as ApiError).isOffline).toBe(true);
    expect(handler).not.toHaveBeenCalled();
  });
});
