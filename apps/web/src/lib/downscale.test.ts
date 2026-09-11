/**
 * The downscale must never be able to lose a photograph.
 *
 * That is the whole risk of this module: it sits between the teacher's camera and
 * the only copy of a class's work, so every branch that cannot produce a smaller
 * image has to produce the ORIGINAL one. A downscale that returns `null`, or
 * throws, or silently drops a file the browser could not decode, turns a slow
 * upload into a lost pile — and the pile may be the only record of a test.
 *
 * jsdom has no canvas and no `createImageBitmap`, which makes it the right place
 * to test exactly that: every fallback path is live here by default.
 */

import { describe, expect, it, vi } from 'vitest';

import { MAX_EDGE_PX, downscaleAll, downscaleImage } from './downscale';

function file(name: string, type: string, bytes = 1024): File {
  return new File([new Uint8Array(bytes)], name, { type });
}

describe('downscaling a photograph', () => {
  it('returns a PDF untouched', async () => {
    const pdf = file('copies.pdf', 'application/pdf');
    await expect(downscaleImage(pdf)).resolves.toBe(pdf);
  });

  it('returns an SVG untouched', async () => {
    const svg = file('drawing.svg', 'image/svg+xml');
    await expect(downscaleImage(svg)).resolves.toBe(svg);
  });

  /** The load-bearing one. jsdom cannot decode, so this exercises the catch. */
  it('returns the original when the browser cannot decode it', async () => {
    const photo = file('copie-1.jpg', 'image/jpeg');
    const out = await downscaleImage(photo);
    expect(out).toBe(photo);
  });

  it('returns the original when there is no document at all', async () => {
    const photo = file('copie-1.jpg', 'image/jpeg');
    await expect(downscaleImage(photo)).resolves.toBe(photo);
  });

  /** An unexpected throw anywhere inside is still the original file, because the
   *  alternative is a pile that never arrives. */
  it('swallows an unexpected failure rather than rejecting', async () => {
    vi.stubGlobal('createImageBitmap', () => {
      throw new Error('boom');
    });
    try {
      const photo = file('copie-1.jpg', 'image/jpeg');
      await expect(downscaleImage(photo)).resolves.toBe(photo);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  /**
   * The happy path, with the browser stubbed: a 4000 px photograph comes back as
   * a 2000 px JPEG, and the arithmetic keeps the aspect ratio.
   *
   * jsdom has neither `createImageBitmap` nor a canvas, so both are supplied here.
   * What is being tested is this module's decisions — the scale factor, the
   * rename, the refusal to ship a larger file — not the browser's encoder.
   */
  it('halves a 4000 px photograph to 2000 px and keeps the ratio', async () => {
    const drawn: { w: number; h: number }[] = [];
    vi.stubGlobal('createImageBitmap', () =>
      Promise.resolve({ width: 4000, height: 3000, close: () => {} }),
    );
    const canvas = {
      width: 0,
      height: 0,
      getContext: () => ({
        imageSmoothingEnabled: false,
        imageSmoothingQuality: 'low',
        drawImage: () => drawn.push({ w: canvas.width, h: canvas.height }),
      }),
      // Far smaller than the 1 MB original, so the result is worth shipping.
      toBlob: (cb: (b: Blob) => void) => cb(new Blob([new Uint8Array(50_000)])),
    };
    const create = vi.spyOn(document, 'createElement').mockReturnValue(canvas as never);

    try {
      const photo = file('copie-1.jpeg', 'image/jpeg', 1_000_000);
      const out = await downscaleImage(photo);

      expect(out).not.toBe(photo);
      expect(out.type).toBe('image/jpeg');
      expect(out.size).toBeLessThan(photo.size);
      // Renamed to match the new encoding, stem preserved so the progress list
      // still shows something the teacher recognises.
      expect(out.name).toBe('copie-1.jpg');
      expect(drawn).toEqual([{ w: 2000, h: 1500 }]);
    } finally {
      create.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  /** An image already small enough is not re-encoded, so it never loses a
   *  generation and a clean scan stays clean. */
  it('leaves an image already under the threshold alone', async () => {
    vi.stubGlobal('createImageBitmap', () =>
      Promise.resolve({ width: 1200, height: 900, close: () => {} }),
    );
    try {
      const photo = file('scan.png', 'image/png', 200_000);
      await expect(downscaleImage(photo)).resolves.toBe(photo);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  /** Re-encoding can enlarge an already-optimised JPEG. Shipping the bigger of
   *  the two would be the opposite of the point. */
  it('keeps the original when the re-encode came out larger', async () => {
    vi.stubGlobal('createImageBitmap', () =>
      Promise.resolve({ width: 4000, height: 3000, close: () => {} }),
    );
    const canvas = {
      width: 0,
      height: 0,
      getContext: () => ({ drawImage: () => {} }),
      toBlob: (cb: (b: Blob) => void) => cb(new Blob([new Uint8Array(900_000)])),
    };
    const create = vi.spyOn(document, 'createElement').mockReturnValue(canvas as never);
    try {
      const photo = file('copie-1.jpg', 'image/jpeg', 500_000);
      await expect(downscaleImage(photo)).resolves.toBe(photo);
    } finally {
      create.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it('exposes a long edge the detector can still work from', () => {
    // ~170 px per A4 inch. Below about 1200 the bubble grid stops resolving.
    expect(MAX_EDGE_PX).toBeGreaterThanOrEqual(1600);
  });
});

describe('downscaling a pile', () => {
  it('returns one file per input, in order, losing none', async () => {
    const files = [
      file('a.jpg', 'image/jpeg'),
      file('b.pdf', 'application/pdf'),
      file('c.png', 'image/png'),
    ];

    const out = await downscaleAll(files);

    expect(out).toHaveLength(3);
    expect(out.map((f) => f.name)).toEqual(['a.jpg', 'b.pdf', 'c.png']);
  });

  it('returns an empty pile for an empty pile', async () => {
    await expect(downscaleAll([])).resolves.toEqual([]);
  });
});
