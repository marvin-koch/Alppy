import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react';
import { cx } from '../lib/cx';
import { useFieldControl } from './Field';

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
  /** Force the invalid state without a `Field` above. */
  invalid?: boolean;
  /** Digits that get compared (scores, UIDs) line up. */
  numeric?: boolean;
}

/** The sunken field: 2px border, radius md, focus halo (DESIGN.md §6). */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { leadingIcon, trailingIcon, invalid, numeric = false, className, id, required, ...rest },
  ref,
) {
  const aria = useFieldControl({
    id,
    describedBy: rest['aria-describedby'],
    invalid,
    required,
  });

  const input = (
    <input
      ref={ref}
      {...rest}
      {...aria}
      {...(numeric ? { 'data-numeric': '' } : {})}
      className={cx(
        'ard-input',
        leadingIcon && 'pl-11',
        trailingIcon && 'pr-11',
        !leadingIcon && !trailingIcon && className,
      )}
    />
  );

  if (!leadingIcon && !trailingIcon) return input;

  return (
    <span className={cx('relative block', className)}>
      {leadingIcon ? (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-ink-500"
        >
          {leadingIcon}
        </span>
      ) : null}
      {input}
      {trailingIcon ? (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-ink-500"
        >
          {trailingIcon}
        </span>
      ) : null}
    </span>
  );
});
