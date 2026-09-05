import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../../lib/cx';
import { IconAi } from '../../icons/set';

export interface AiBadgeProps extends HTMLAttributes<HTMLSpanElement> {
  /**
   * The word, in the teacher's language: "IA" / "KI" / "AI". Required — the
   * mandarin alone must never be what tells a teacher a machine wrote this.
   */
  label: string;
  size?: 'sm' | 'md';
}

/**
 * THE one component allowed the mandarin accent (DESIGN.md §1, §2): it marks
 * an AI-generated exercise, and nothing else in the product may use
 * `--c-accent-*`. It always carries its word as well as its colour.
 */
export const AiBadge = forwardRef<HTMLSpanElement, AiBadgeProps>(function AiBadge(
  { label, size = 'md', className, ...rest },
  ref,
) {
  return (
    <span
      ref={ref}
      data-variant="accent"
      data-ai-generated=""
      className={cx('ard-chip', size === 'sm' && 'px-2 py-0.5', className)}
      {...rest}
    >
      <IconAi size={size === 'sm' ? 12 : 14} strokeWidth={2.4} aria-hidden="true" />
      {label}
    </span>
  );
});
