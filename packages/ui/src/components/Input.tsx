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
  {
    leadingIcon,
    trailingIcon,
    invalid,
    numeric = false,
    className,
    id,
    required,
    onWheel,
    ...rest
  },
  ref,
) {
  const aria = useFieldControl({
    id,
    describedBy: rest['aria-describedby'],
    invalid,
    required,
  });

  /**
   * A scroll over a focused number input must not change its value (G21).
   *
   * The browser treats a wheel event on a focused `type="number"` as a step, so
   * scrolling down a long form past a field the teacher had just clicked silently
   * edited it — a barème, a number of lines, a group count — with no keystroke and
   * nothing on screen to say it happened. Blurring is the standard remedy and the
   * honest one: the teacher was scrolling, not editing, so the field should stop
   * being the thing receiving input.
   *
   * Centrally here rather than per field, so every current and future number input
   * is covered. A caller's own `onWheel` still runs.
   */
  const handleWheel: InputProps['onWheel'] = (event) => {
    onWheel?.(event);
    if (rest.type === 'number' && document.activeElement === event.currentTarget) {
      event.currentTarget.blur();
    }
  };

  const input = (
    <input
      ref={ref}
      {...rest}
      {...aria}
      onWheel={handleWheel}
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
