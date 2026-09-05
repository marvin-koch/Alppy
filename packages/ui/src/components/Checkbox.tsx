import { forwardRef, useEffect, useId, useRef, type InputHTMLAttributes, type ReactNode } from 'react';
import { cx } from '../lib/cx';
import { mergeRefs } from '../lib/refs';
import { IconCheck, IconMinus } from '../icons/set';
import { useFieldContext } from './Field';

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'size'> {
  /** Checkboxes carry their own label. Wrap a GROUP of them in `Field as="fieldset"`. */
  label: ReactNode;
  description?: ReactNode;
  /** Tri-state: "some of this class is selected". */
  indeterminate?: boolean;
  invalid?: boolean;
}

/**
 * A real `<input type="checkbox">` — native semantics, native keyboard — with
 * the box drawn by us. The whole row is a 44px touch target.
 */
export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { label, description, indeterminate = false, invalid, className, id, disabled, ...rest },
  ref,
) {
  const field = useFieldContext();
  const generated = useId();
  const inputId = id ?? `${generated}-checkbox`;
  const descriptionId = description ? `${generated}-description` : undefined;
  const inner = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (inner.current) inner.current.indeterminate = indeterminate;
  }, [indeterminate]);

  const describedBy =
    [rest['aria-describedby'], descriptionId, field?.describedBy].filter(Boolean).join(' ') || undefined;

  return (
    <div className={cx('flex min-h-11 items-start gap-3 py-1.5', className)}>
      <span className="relative mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center">
        <input
          ref={mergeRefs(ref, inner)}
          id={inputId}
          type="checkbox"
          disabled={disabled}
          {...rest}
          aria-describedby={describedBy}
          aria-invalid={invalid ?? field?.invalid ? true : undefined}
          className={cx(
            'peer absolute inset-0 h-full w-full cursor-pointer appearance-none rounded-sm border-2 bg-surface',
            'border-line-strong transition-colors',
            'checked:border-primary-500 checked:bg-primary-500',
            'indeterminate:border-primary-500 indeterminate:bg-primary-500',
            'aria-[invalid=true]:border-danger-500',
            'disabled:cursor-not-allowed disabled:bg-surface-2',
          )}
        />
        {indeterminate ? (
          <IconMinus
            size={16}
            strokeWidth={3}
            className="pointer-events-none relative text-surface opacity-0 peer-[:indeterminate]:opacity-100"
          />
        ) : (
          <IconCheck
            size={16}
            strokeWidth={3}
            className="pointer-events-none relative text-surface opacity-0 peer-checked:opacity-100"
          />
        )}
      </span>
      <label htmlFor={inputId} className={cx('cursor-pointer text-body', disabled && 'text-ink-300')}>
        <span className="block text-ink-900">{label}</span>
        {description ? (
          <span id={descriptionId} className="block text-body-s text-ink-500">
            {description}
          </span>
        ) : null}
      </label>
    </div>
  );
});
