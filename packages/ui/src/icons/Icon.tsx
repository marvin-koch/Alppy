import { forwardRef, type ReactNode, type SVGProps } from 'react';
import { cx } from '../lib/cx';

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'width' | 'height' | 'ref'> {
  /** Rendered box, px. 24 is the drawing grid; scale, never redraw. */
  size?: number;
  /** Stroke width on the 24px grid (DESIGN.md §7: 2–2.4). */
  strokeWidth?: number;
  /**
   * Accessible name. Omit for a decorative icon sitting next to real text —
   * it is then `aria-hidden`. Pass a string only when the icon is the only
   * carrier of meaning. The library ships no strings: the app supplies it.
   */
  title?: string;
}

/**
 * Shared wrapper for every icon in the repo. No icon library, no borrowed
 * marks (DESIGN.md §7). `currentColor` everywhere — an icon never picks a
 * colour, it inherits the ink of its context.
 */
export const Icon = forwardRef<SVGSVGElement, IconProps>(function Icon(
  { size = 24, strokeWidth = 2.2, title, className, children, ...rest },
  ref,
) {
  const named = typeof title === 'string' && title.length > 0;
  return (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
      role={named ? 'img' : undefined}
      aria-hidden={named ? undefined : true}
      className={cx('inline-block shrink-0 align-middle', className)}
      {...rest}
    >
      {named ? <title>{title}</title> : null}
      {children}
    </svg>
  );
});

export type IconComponent = typeof Icon;

/** Build an icon component from its geometry. Keeps every icon one line of code. */
export function createIcon(displayName: string, geometry: ReactNode): IconComponent {
  const Component = forwardRef<SVGSVGElement, IconProps>(function AlppyIcon(props, ref) {
    return (
      <Icon ref={ref} {...props}>
        {geometry}
      </Icon>
    );
  });
  Component.displayName = displayName;
  return Component;
}
