import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cx } from '../lib/cx';
import type { ButtonSize, ButtonVariant } from './Button';

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> {
  /** The icon. Always decorative — `label` carries the accessible name. */
  icon: ReactNode;
  /** Required: an icon-only control with no name is unusable with a screen reader. */
  label: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Renders the label as visible text next to the icon from `sm` upward. */
  showLabelFrom?: 'sm' | 'md' | 'lg';
}

const LABEL_VISIBILITY: Record<'sm' | 'md' | 'lg', string> = {
  sm: 'hidden sm:inline',
  md: 'hidden md:inline',
  lg: 'hidden lg:inline',
};

/** Square button. 44px hit area at every size — phone in the classroom. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, label, variant = 'secondary', size = 'md', showLabelFrom, className, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      data-variant={variant}
      data-size={size === 'md' ? undefined : size}
      title={showLabelFrom ? undefined : label}
      className={cx('ard-btn min-w-11 px-3', showLabelFrom ? 'gap-2' : 'aspect-square px-0', className)}
      {...rest}
    >
      {icon}
      {/* aria-label carries the name; the visible copy is decorative so the
          label is never announced twice. */}
      {showLabelFrom ? (
        <span aria-hidden="true" className={LABEL_VISIBILITY[showLabelFrom]}>
          {label}
        </span>
      ) : null}
    </button>
  );
});
