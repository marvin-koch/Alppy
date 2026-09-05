import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../lib/cx';

export interface EmptyStateProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  /** An illustration from `src/illustrations`. Decorative; calm mode drops it. */
  illustration?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  /** The one thing to do next. */
  action?: ReactNode;
  secondaryAction?: ReactNode;
  size?: 'sm' | 'md';
}

/** Every screen ships one (DESIGN.md §6). An empty screen still explains itself. */
export const EmptyState = forwardRef<HTMLDivElement, EmptyStateProps>(function EmptyState(
  { illustration, title, description, action, secondaryAction, size = 'md', className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cx(
        'flex flex-col items-center gap-3 text-center',
        size === 'md' ? 'px-4 py-10 sm:py-14' : 'px-3 py-6',
        className,
      )}
      {...rest}
    >
      {illustration}
      <h3 className="font-display text-h2 font-bold text-ink-900">{title}</h3>
      {description ? (
        <p className="max-w-prose text-body text-ink-700">{description}</p>
      ) : null}
      {children}
      {action || secondaryAction ? (
        <div className="mt-2 flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:justify-center">
          {action}
          {secondaryAction}
        </div>
      ) : null}
    </div>
  );
});
