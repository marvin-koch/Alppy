import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../lib/cx';
import type { StatusVariant } from '../lib/types';
import { IconCross } from '../icons/set';

interface ChipBaseProps extends HTMLAttributes<HTMLSpanElement> {
  /**
   * No `accent` here on purpose: the mandarin belongs to AI-generated
   * exercises and is reachable only through `AiBadge`.
   */
  variant?: StatusVariant;
  leadingIcon?: ReactNode;
}

type ChipRemoval =
  | { onRemove: () => void; removeLabel: string }
  | { onRemove?: undefined; removeLabel?: undefined };

export type ChipProps = ChipBaseProps & ChipRemoval;

/** Label token: `-100` background, `-600` ink, border = colour at 40%. */
export const Chip = forwardRef<HTMLSpanElement, ChipProps>(function Chip(
  { variant = 'neutral', leadingIcon, onRemove, removeLabel, className, children, ...rest },
  ref,
) {
  return (
    <span
      ref={ref}
      data-variant={variant === 'neutral' ? undefined : variant}
      className={cx('ard-chip', className)}
      {...rest}
    >
      {leadingIcon}
      {children}
      {onRemove ? (
        <button
          type="button"
          onClick={onRemove}
          aria-label={removeLabel}
          className="-mr-1 ml-1 inline-flex h-6 w-6 items-center justify-center rounded-pill hover:bg-primary-100"
        >
          <IconCross size={14} strokeWidth={2.4} />
        </button>
      ) : null}
    </span>
  );
});
