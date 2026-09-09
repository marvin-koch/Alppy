import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cx } from '../lib/cx';
import { Spinner } from './Spinner';

export type ButtonVariant = 'primary' | 'secondary' | 'accent' | 'danger' | 'ghost';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /**
   * `accent` is the mandarin. It is legitimate on exactly one action: the one
   * that produces or applies AI-generated exercises (F4). Everywhere else it
   * loses its meaning — use `primary`.
   */
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Full width. Still 44px min-height: the touch target is not negotiable. */
  block?: boolean;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
  /** Disables the button and marks it `aria-busy`. */
  loading?: boolean;
  /** Announced while `loading` — the app supplies the string. */
  busyLabel?: string;
}

/**
 * The pressable button (DESIGN.md §6): a solid edge that collapses under the
 * press. Label in Fredoka — the `.ard-btn` recipe sets it; never override it.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    block = false,
    leadingIcon,
    trailingIcon,
    loading = false,
    busyLabel,
    disabled,
    className,
    children,
    type = 'button',
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      data-variant={variant}
      data-size={size === 'md' ? undefined : size}
      data-block={block ? 'true' : undefined}
      disabled={disabled === true || loading}
      aria-busy={loading || undefined}
      className={cx('ard-btn', className)}
      {...rest}
    >
      {loading ? <Spinner /> : leadingIcon}
      {children}
      {loading && busyLabel ? <span className="visually-hidden">{busyLabel}</span> : null}
      {loading ? null : trailingIcon}
    </button>
  );
});
