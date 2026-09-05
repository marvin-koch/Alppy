import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../lib/cx';

export interface DividerProps extends HTMLAttributes<HTMLDivElement> {
  orientation?: 'horizontal' | 'vertical';
  /** Optional caption sitting in the rule. Supplied by the app. */
  label?: ReactNode;
}

export const Divider = forwardRef<HTMLDivElement, DividerProps>(function Divider(
  { orientation = 'horizontal', label, className, ...rest },
  ref,
) {
  if (orientation === 'vertical') {
    return (
      <div
        ref={ref}
        role="separator"
        aria-orientation="vertical"
        className={cx('w-px self-stretch bg-line', className)}
        {...rest}
      />
    );
  }

  if (label) {
    return (
      <div
        ref={ref}
        role="separator"
        aria-orientation="horizontal"
        className={cx('flex items-center gap-3 text-label text-ink-500 uppercase', className)}
        {...rest}
      >
        <span aria-hidden="true" className="h-px flex-1 bg-line" />
        {label}
        <span aria-hidden="true" className="h-px flex-1 bg-line" />
      </div>
    );
  }

  return (
    <div
      ref={ref}
      role="separator"
      aria-orientation="horizontal"
      className={cx('h-px w-full bg-line', className)}
      {...rest}
    />
  );
});
