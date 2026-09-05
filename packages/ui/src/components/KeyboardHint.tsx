import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../lib/cx';

export interface KeyboardHintProps extends HTMLAttributes<HTMLSpanElement> {
  /** Key names in press order, e.g. `['⌘', 'K']` or `['Alt', '→']`. */
  keys: string[];
  /** Accessible name for the whole combination — the app supplies the string. */
  label?: string;
  size?: 'sm' | 'md';
}

/**
 * A key combination. The separator is a symbol, not a word, so the component
 * stays free of translated strings.
 */
export const KeyboardHint = forwardRef<HTMLSpanElement, KeyboardHintProps>(function KeyboardHint(
  { keys, label, size = 'sm', className, ...rest },
  ref,
) {
  return (
    <span
      ref={ref}
      role={label ? 'img' : undefined}
      aria-label={label}
      className={cx('inline-flex items-center gap-1 align-middle', className)}
      {...rest}
    >
      {keys.map((key, index) => (
        <span key={`${key}-${index}`} className="inline-flex items-center gap-1">
          {index > 0 ? (
            <span aria-hidden="true" className="text-ink-300">
              +
            </span>
          ) : null}
          <kbd
            className={cx(
              'inline-flex items-center justify-center rounded-sm border border-line-strong bg-surface-2',
              'font-mono font-bold text-ink-700 shadow-[0_1px_0_0_var(--c-line-strong)]',
              size === 'sm' ? 'min-w-6 px-1.5 py-0.5 text-body-s' : 'min-w-7 px-2 py-1 text-body',
            )}
          >
            {key}
          </kbd>
        </span>
      ))}
    </span>
  );
});
