import { forwardRef, type SVGProps } from 'react';
import { cx } from '../lib/cx';

export interface AlppyMarkProps extends Omit<SVGProps<SVGSVGElement>, 'width' | 'height' | 'ref'> {
  /** Rendered box, px. */
  size?: number;
  /**
   * `brand` — the slate in violet, chalk, and the mandarin dot.
   * `mono`  — everything in `currentColor` for print, the footer, a favicon
   *           mask, or anywhere the mark must survive one ink.
   */
  tone?: 'brand' | 'mono';
  /**
   * Accessible name. Omit when the mark sits beside the wordmark (the text
   * carries the name) — it is then `aria-hidden`. The app supplies the string.
   */
  title?: string;
}

/**
 * The Alppy mark: a slate (rectangle, radius 7) crossed by a chalk stroke that
 * carries an alpine notch, plus the mandarin dot. Drawn here, not licensed
 * (DESIGN.md §7). The mandarin dot is the one sanctioned use of the accent
 * outside AI-generated content.
 */
export const AlppyMark = forwardRef<SVGSVGElement, AlppyMarkProps>(function AlppyMark(
  { size = 32, tone = 'brand', title, className, ...rest },
  ref,
) {
  const named = typeof title === 'string' && title.length > 0;
  const slate = tone === 'mono' ? 'none' : 'var(--c-primary-500)';
  const slateEdge = tone === 'mono' ? 'currentColor' : 'var(--c-primary-600)';
  const chalk = tone === 'mono' ? 'currentColor' : 'var(--c-surface)';
  const dot = tone === 'mono' ? 'currentColor' : 'var(--c-accent-500)';

  return (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 40 40"
      width={size}
      height={size}
      fill="none"
      focusable="false"
      role={named ? 'img' : undefined}
      aria-hidden={named ? undefined : true}
      className={cx('block shrink-0', className)}
      {...rest}
    >
      {named ? <title>{title}</title> : null}
      <rect x="3" y="7" width="34" height="26" rx="7" fill={slate} stroke={slateEdge} strokeWidth="2" />
      <path
        d="M9 27h4l5.5-11 3.5 6 3-4.5L29.5 27H31"
        fill="none"
        stroke={chalk}
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="31" cy="12.5" r="3.2" fill={dot} />
    </svg>
  );
});
