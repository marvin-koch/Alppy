'use client';

/**
 * Shrink a photograph before it is uploaded.
 *
 * A modern phone camera produces 8–12 MP JPEGs, and a pile is up to 120 pages
 * (the API's cap). That is the single largest available win on upload time and
 * on the failure rate over a school's connection, and it costs the detector
 * nothing: registration works from the four fiducials and then reads bubbles off
 * a deskewed page, so what it needs is enough resolution to resolve a fill
 * ratio, not enough to read the paper's texture.
 *
 * 2000 px on the long edge is about 170 px per A4 inch — comfortably more than
 * the ~100 px/inch the bubble grid needs at `SHEET_LAYOUT`'s pitch, with headroom
 * for a photograph taken at an angle, where the far edge of the page is
 * compressed and loses resolution before the near edge does.
 *
 * What this deliberately does NOT do:
 *
 * - **Touch a PDF.** A teacher who scanned to PDF has already produced a
 *   reasonable file, and re-encoding it here would mean rasterising it in the
 *   browser — which is both a large dependency and a quality loss on the one
 *   input that arrived clean.
 * - **Guarantee anything.** Every failure path returns the ORIGINAL file. A
 *   browser that will not decode an image, a canvas the OS refuses, an
 *   `image/heic` Safari hands over without a decoder: in all of those the upload
 *   proceeds full-size and slow, which is worse than fast and impossible. The
 *   server remains the only real limit.
 * - **Enlarge.** An image already under the threshold is returned untouched, so
 *   a small scan is never re-encoded and never loses a generation.
 */

/** The long edge, in pixels, a photograph is reduced to. */
export const MAX_EDGE_PX = 2000;

/**
 * JPEG quality for the re-encode.
 *
 * 0.82 is where a bubble's edge stays crisp while the file is a fraction of the
 * original. Higher wastes the win; lower starts putting ringing artefacts around
 * pencil strokes, which is exactly the signal the detector measures.
 */
const JPEG_QUALITY = 0.82;

function isDownscalable(file: File): boolean {
  // Not PDFs, and not SVG (no meaningful pixel size, and rasterising one is a
  // security question rather than a size one).
  return file.type.startsWith('image/') && file.type !== 'image/svg+xml';
}

/** Decode to something `drawImage` accepts, preferring the path that does not
 *  need the DOM. `createImageBitmap` also applies EXIF orientation for us. */
async function decode(file: File): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof createImageBitmap === 'function') {
    return createImageBitmap(file, { imageOrientation: 'from-image' });
  }
  const url = URL.createObjectURL(file);
  try {
    return await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('decode failed'));
      img.src = url;
    });
  } finally {
    // Revoked after the decode either way: the bitmap no longer needs the blob,
    // and leaving it attached leaks one object URL per photograph in a pile.
    URL.revokeObjectURL(url);
  }
}

async function toBlob(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY));
}

/**
 * One photograph, reduced to `MAX_EDGE_PX` on its long edge.
 *
 * Returns the original file on every failure, and whenever shrinking it would
 * not help.
 */
export async function downscaleImage(file: File, maxEdge = MAX_EDGE_PX): Promise<File> {
  if (!isDownscalable(file)) return file;
  if (typeof document === 'undefined') return file;

  try {
    const source = await decode(file);
    const width = 'width' in source ? source.width : 0;
    const height = 'height' in source ? source.height : 0;
    if (width === 0 || height === 0) return file;

    const longEdge = Math.max(width, height);
    if (longEdge <= maxEdge) {
      if ('close' in source) source.close();
      return file;
    }

    const scale = maxEdge / longEdge;
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    const ctx = canvas.getContext('2d');
    if (!ctx) return file;
    // The default is already 'low' in some engines; a page of pencil marks being
    // reduced 4× needs the good filter or thin strokes drop out entirely.
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    if ('close' in source) source.close();

    const blob = await toBlob(canvas);
    if (!blob) return file;
    // Bigger after re-encoding than before is possible — an already-optimised
    // JPEG, or a screenshot-like image — and shipping the larger of the two would
    // be the opposite of the point.
    if (blob.size >= file.size) return file;

    return new File([blob], renameToJpeg(file.name), {
      type: 'image/jpeg',
      lastModified: file.lastModified,
    });
  } catch {
    // Every decode, canvas and encode failure lands here, and every one of them
    // means "upload what the teacher actually chose".
    return file;
  }
}

/** The name keeps its stem, because the teacher recognises it in the progress
 *  list; only the extension follows the new encoding. */
function renameToJpeg(name: string): string {
  const stem = name.replace(/\.[^./\\]+$/, '');
  return `${stem || 'photo'}.jpg`;
}

/** A whole pile, in order. Sequential on purpose: decoding twenty 12 MP images
 *  at once is how a phone browser runs out of memory mid-upload. */
export async function downscaleAll(files: File[], maxEdge = MAX_EDGE_PX): Promise<File[]> {
  const out: File[] = [];
  for (const file of files) out.push(await downscaleImage(file, maxEdge));
  return out;
}
