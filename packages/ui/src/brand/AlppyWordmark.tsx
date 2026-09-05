import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../lib/cx';

export interface AlppyWordmarkProps extends HTMLAttributes<HTMLSpanElement> {
  size?: 'sm' | 'md' | 'lg';
}

const SIZE: Record<'sm' | 'md' | 'lg', string> = {
  sm: 'text-h3',
  md: 'text-h2',
  lg: 'text-h1',
};

/**
 * "Alppy" in Fredoka 700 — the wordmark sits BESIDE the mark, never inside it
 * (DESIGN.md §7). A proper noun, so it is not a translated string.
 */
export const AlppyWordmark = forwardRef<HTMLSpanElement, AlppyWordmarkProps>(function AlppyWordmark(
  { size = 'md', className, ...rest },
  ref,
) {
  return (
    <span
      ref={ref}
      className={cx('font-display font-bold tracking-tight text-ink-900', SIZE[size], className)}
      {...rest}
    >
      Alppy
    </span>
  );
});
