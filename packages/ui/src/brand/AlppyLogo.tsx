import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../lib/cx';
import { AlppyMark } from './AlppyMark';
import { AlppyWordmark } from './AlppyWordmark';

export interface AlppyLogoProps extends HTMLAttributes<HTMLSpanElement> {
  size?: 'sm' | 'md' | 'lg';
  /** Passed through to the mark. See AlppyMarkProps. */
  tone?: 'primary' | 'ink' | 'knockout' | 'mono';
  /** Hide the wordmark (collapsed rail, favicon-sized headers). */
  markOnly?: boolean;
  /** Accessible name used only when `markOnly` — the app supplies the string. */
  title?: string;
}

const MARK_PX: Record<'sm' | 'md' | 'lg', number> = { sm: 24, md: 32, lg: 44 };

/** Mark + wordmark, side by side. Never the wordmark inside the slate. */
export const AlppyLogo = forwardRef<HTMLSpanElement, AlppyLogoProps>(function AlppyLogo(
  { size = 'md', tone = 'primary', markOnly = false, title, className, ...rest },
  ref,
) {
  return (
    <span ref={ref} className={cx('inline-flex items-center gap-2', className)} {...rest}>
      <AlppyMark size={MARK_PX[size]} tone={tone} {...(markOnly && title ? { title } : {})} />
      {markOnly ? null : <AlppyWordmark size={size} />}
    </span>
  );
});
