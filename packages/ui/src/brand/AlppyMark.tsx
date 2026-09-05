import { forwardRef, type SVGProps } from 'react';
import { cx } from '../lib/cx';

export interface AlppyMarkProps extends Omit<SVGProps<SVGSVGElement>, 'width' | 'height' | 'ref'> {
  /** Rendered box, px. Below 24 the `small` cut is used automatically. */
  size?: number;
  /**
   * `primary`  — violet slate, white chalk. The default.
   * `ink`      — on light backgrounds where the violet would compete.
   * `knockout` — no plate, strokes only, for use inside an existing container.
   * `mono`     — one ink, `currentColor`: print, the footer, a favicon mask.
   */
  tone?: 'primary' | 'ink' | 'knockout' | 'mono';
  /**
   * Accessible name. Omit when the mark sits beside the wordmark — the text
   * carries the name and the mark is then `aria-hidden`. The library ships no
   * strings: the app supplies it.
   */
  title?: string;
}

/**
 * The Alppy mark — **"Le sourire"**.
 *
 * Two slopes meeting at a summit with a smile in the valley between them. The
 * crossbar of the **A** is the smile: one move, no added element. It reads as a
 * letter, as two peaks, and as a face turned friendly.
 *
 * Geometry transcribed from the shipped brand library
 * (`docs/design/alppy-brand-assets/brand/logo/`), not redrawn: 64-unit grid,
 * slate inset 3u with radius 17u, stroke 6.2u round-capped, feet at 16.2u and
 * 47.8u on a 46.8u baseline, apex at 16.8u. The smile is a quadratic with an
 * 18.8u chord at height 35.2u and a 5u rise, its ends on the axis of the
 * slopes, so all three strokes read as one continuous drawing.
 *
 * **The mark carries no mandarin accent.** The accent is functional inside the
 * product, where it means AI-generated content; spending it on the logo would
 * cost it that meaning.
 *
 * Never stretch, recolour, rotate, or shadow it.
 */
export const AlppyMark = forwardRef<SVGSVGElement, AlppyMarkProps>(function AlppyMark(
  { size = 32, tone = 'primary', title, className, ...rest },
  ref,
) {
  const named = typeof title === 'string' && title.length > 0;

  // Below 24px the smile lifts and opens, or it closes up into a blot.
  const small = size < 24;
  const smile = small ? 'M23.24 34.0 Q32 43.2 40.76 34.0' : 'M22.61 35.2 Q32 45.2 41.39 35.2';
  const strokeWidth = small ? 6.0 : 6.2;

  const plate = tone === 'knockout' || tone === 'mono' ? null : tone === 'ink'
    ? 'var(--c-ink-900)'
    : 'var(--c-primary-500)';
  const chalk =
    tone === 'mono' || tone === 'knockout' ? 'currentColor' : 'var(--c-surface)';

  return (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      width={size}
      height={size}
      focusable="false"
      role={named ? 'img' : undefined}
      aria-hidden={named ? undefined : true}
      className={cx('inline-block shrink-0 align-middle', className)}
      {...rest}
    >
      {named ? <title>{title}</title> : null}
      {plate ? <rect x="3" y="3" width="58" height="58" rx="17" fill={plate} /> : null}
      <g
        fill="none"
        stroke={tone === 'knockout' ? 'var(--c-primary-500)' : chalk}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M16.2 46.8 L32 16.8 L47.8 46.8" />
        <path d={smile} />
      </g>
    </svg>
  );
});
