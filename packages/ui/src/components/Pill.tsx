import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../lib/cx';

export interface PillProps extends HTMLAttributes<HTMLSpanElement> {
  /** Numeric pills align their digits — counts are compared at a glance. */
  numeric?: boolean;
  emphasis?: 'quiet' | 'strong';
}

/** A count or a short neutral value. Quieter than a Chip, never uppercase. */
export const Pill = forwardRef<HTMLSpanElement, PillProps>(function Pill(
  { numeric = false, emphasis = 'quiet', className, children, ...rest },
  ref,
) {
  return (
    <span
      ref={ref}
      {...(numeric ? { 'data-numeric': '' } : {})}
      className={cx(
        'inline-flex min-w-6 items-center justify-center gap-1 rounded-pill px-2 py-0.5 text-body-s font-bold',
        emphasis === 'strong'
          ? 'bg-primary-500 text-surface'
          : 'border border-line bg-surface-2 text-ink-700',
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
});
