import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../lib/cx';

export interface PanelProps extends HTMLAttributes<HTMLDivElement> {
  /** Sunken variant — table headers, a quoted excerpt, a read-only region. */
  sunken?: boolean;
}

/**
 * A panel is a SUBDIVISION of the object you are already on: radius md,
 * border, no shadow (DESIGN.md §6).
 */
export const Panel = forwardRef<HTMLDivElement, PanelProps>(function Panel(
  { sunken = false, className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      data-sunken={sunken ? 'true' : undefined}
      className={cx('ard-panel', className)}
      {...rest}
    >
      {children}
    </div>
  );
});
