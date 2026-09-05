import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../lib/cx';
import { IconCheck } from '../icons/set';

export interface StepperStep {
  id: string;
  label: ReactNode;
  description?: ReactNode;
}

export interface StepperProps extends HTMLAttributes<HTMLOListElement> {
  steps: StepperStep[];
  /** Zero-based index of the step in progress. */
  current: number;
  /**
   * Screen-reader-only status words, one per state. Optional, and supplied by
   * the app — the library carries no strings.
   */
  statusLabels?: { complete: string; current: string; upcoming: string };
  /** Ordered stepper: numbers stay visible below `sm` where labels are hidden. */
  compactBelow?: 'sm' | 'md';
}

/**
 * Linear progress through a flow (upload → detect → review → confirm).
 * State is carried by the numeral, the check and a text status — never by
 * colour alone.
 */
export const Stepper = forwardRef<HTMLOListElement, StepperProps>(function Stepper(
  { steps, current, statusLabels, compactBelow = 'sm', className, ...rest },
  ref,
) {
  const hideLabel = compactBelow === 'sm' ? 'hidden sm:block' : 'hidden md:block';
  return (
    <ol ref={ref} className={cx('flex items-start gap-2 sm:gap-4', className)} {...rest}>
      {steps.map((step, index) => {
        const state = index < current ? 'complete' : index === current ? 'current' : 'upcoming';
        return (
          <li
            key={step.id}
            aria-current={state === 'current' ? 'step' : undefined}
            className="flex min-w-0 flex-1 flex-col items-center gap-2 text-center"
          >
            <div className="flex w-full items-center gap-2">
              <span aria-hidden="true" className={cx('h-0.5 flex-1', index === 0 ? 'opacity-0' : index <= current ? 'bg-primary-500' : 'bg-line')} />
              <span
                aria-hidden="true"
                className={cx(
                  'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-pill font-display text-body-s font-bold',
                  state === 'complete' && 'bg-primary-500 text-surface',
                  state === 'current' && 'border-2 border-primary-500 bg-primary-100 text-primary-700',
                  state === 'upcoming' && 'border-2 border-line bg-surface text-ink-500',
                )}
              >
                {state === 'complete' ? <IconCheck size={18} /> : index + 1}
              </span>
              <span
                aria-hidden="true"
                className={cx(
                  'h-0.5 flex-1',
                  index === steps.length - 1 ? 'opacity-0' : index < current ? 'bg-primary-500' : 'bg-line',
                )}
              />
            </div>
            <div className={cx('min-w-0', hideLabel)}>
              <p
                className={cx(
                  'truncate text-body-s font-bold',
                  state === 'upcoming' ? 'text-ink-500' : 'text-ink-900',
                )}
              >
                {step.label}
              </p>
              {step.description ? (
                <p className="truncate text-body-s text-ink-500">{step.description}</p>
              ) : null}
            </div>
            {/* The visible label is hidden on a phone, so the same text is kept
                for assistive tech at that size. */}
            <span className={compactBelow === 'sm' ? 'visually-hidden sm:hidden' : 'visually-hidden md:hidden'}>
              {step.label}
            </span>
            {statusLabels ? <span className="visually-hidden">{statusLabels[state]}</span> : null}
          </li>
        );
      })}
    </ol>
  );
});
