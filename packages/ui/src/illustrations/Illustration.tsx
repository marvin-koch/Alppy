import { forwardRef, type ReactNode, type SVGProps } from 'react';
import { cx } from '../lib/cx';

export interface IllustrationProps extends Omit<SVGProps<SVGSVGElement>, 'width' | 'height' | 'ref'> {
  /** Rendered box, px. Drawn on a 120 grid; scale, never redraw. */
  size?: number;
}

/**
 * Flat SVG, 120×120, three colours only (DESIGN.md §7):
 *   fill   `--c-primary-100`
 *   stroke `--c-primary-500`
 *   `--c-accent-500` for the SINGLE point of attention.
 *
 * Always decorative: `aria-hidden` plus `data-decorative`, which calm mode
 * (`:root[data-calm='on']`) removes outright. Never the only carrier of
 * meaning — the surrounding EmptyState/ErrorState text says what is going on.
 */
export const Illustration = forwardRef<SVGSVGElement, IllustrationProps & { children: ReactNode }>(
  function Illustration({ size = 120, className, children, ...rest }, ref) {
    return (
      <svg
        ref={ref}
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 120 120"
        width={size}
        height={size}
        fill="none"
        stroke="var(--c-primary-500)"
        strokeWidth={3}
        strokeLinecap="round"
        strokeLinejoin="round"
        focusable="false"
        aria-hidden="true"
        data-decorative=""
        className={cx('block', className)}
        {...rest}
      >
        {children}
      </svg>
    );
  },
);

export type IllustrationComponent = ReturnType<typeof createIllustration>;

export function createIllustration(displayName: string, geometry: ReactNode) {
  const Component = forwardRef<SVGSVGElement, IllustrationProps>(function AlppyIllustration(props, ref) {
    return (
      <Illustration ref={ref} {...props}>
        {geometry}
      </Illustration>
    );
  });
  Component.displayName = displayName;
  return Component;
}
