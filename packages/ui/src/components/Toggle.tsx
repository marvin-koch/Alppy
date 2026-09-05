import { forwardRef, useId, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cx } from '../lib/cx';
import { useFieldContext } from './Field';

export interface ToggleProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onChange' | 'type'> {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  /** Always present. Hide it visually with `hideLabel` if the context is obvious. */
  label: ReactNode;
  description?: ReactNode;
  hideLabel?: boolean;
  labelPosition?: 'start' | 'end';
}

/**
 * `role="switch"` with `aria-checked` — a real, keyboard-operable control.
 * Used for the four teacher preferences (theme, contrast, motion, calm).
 */
export const Toggle = forwardRef<HTMLButtonElement, ToggleProps>(function Toggle(
  { checked, onCheckedChange, label, description, hideLabel = false, labelPosition = 'start', className, disabled, ...rest },
  ref,
) {
  const generated = useId();
  const labelId = `${generated}-label`;
  const descriptionId = description ? `${generated}-description` : undefined;
  const field = useFieldContext();
  const describedBy = [descriptionId, field?.describedBy].filter(Boolean).join(' ') || undefined;

  const text = (
    <span className={cx('min-w-0 flex-1', hideLabel && 'visually-hidden')}>
      <span id={labelId} className="block text-body text-ink-900">
        {label}
      </span>
      {description ? (
        <span id={descriptionId} className="block text-body-s text-ink-500">
          {description}
        </span>
      ) : null}
    </span>
  );

  return (
    <div
      className={cx(
        'flex min-h-11 items-center gap-3',
        labelPosition === 'end' && 'flex-row-reverse justify-end',
        className,
      )}
    >
      {text}
      <button
        ref={ref}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        aria-describedby={describedBy}
        disabled={disabled}
        onClick={() => onCheckedChange(!checked)}
        className={cx(
          'relative inline-flex h-7 w-12 shrink-0 items-center rounded-pill border-2 transition-colors',
          checked ? 'border-primary-600 bg-primary-500' : 'border-line-strong bg-surface-2',
          'disabled:cursor-not-allowed disabled:opacity-60',
        )}
        {...rest}
      >
        <span
          aria-hidden="true"
          className={cx(
            'inline-block h-5 w-5 rounded-pill transition-transform',
            checked ? 'translate-x-5 bg-surface' : 'translate-x-0.5 bg-ink-300',
          )}
        />
      </button>
    </div>
  );
});
