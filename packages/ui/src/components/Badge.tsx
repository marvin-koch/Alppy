import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../lib/cx';
import type { StatusVariant } from '../lib/types';

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: StatusVariant;
  /** The dot is a second channel next to colour; the text is the third. */
  dot?: boolean;
}

const DOT: Record<StatusVariant, string> = {
  neutral: 'bg-ink-300',
  primary: 'bg-primary-500',
  success: 'bg-success-500',
  warn: 'bg-warn-500',
  danger: 'bg-danger-500',
  info: 'bg-info-500',
};

/**
 * A status marker. Colour is never alone: a badge always carries its own text,
 * and by default a dot as well (DESIGN.md §2).
 */
export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { variant = 'neutral', dot = true, className, children, ...rest },
  ref,
) {
  return (
    <span
      ref={ref}
      data-variant={variant === 'neutral' ? undefined : variant}
      className={cx('ard-chip', className)}
      {...rest}
    >
      {dot ? <span aria-hidden="true" className={cx('h-2 w-2 shrink-0 rounded-pill', DOT[variant])} /> : null}
      {children}
    </span>
  );
});
