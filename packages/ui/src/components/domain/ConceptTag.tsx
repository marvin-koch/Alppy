import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../../lib/cx';

export interface ConceptTagProps extends HTMLAttributes<HTMLSpanElement> {
  /** The curriculum code, e.g. `MA.2.A.1` (LP21) or `MSN 32` (PER). */
  code: string;
  /** Optional plain-language name beside the code. */
  label?: ReactNode;
}

/**
 * Official curriculum data is NEVER coloured (DESIGN.md §6). The code sits in
 * an outline pill, in mono, so it reads as a reference and not as a status.
 */
export const ConceptTag = forwardRef<HTMLSpanElement, ConceptTagProps>(function ConceptTag(
  { code, label, className, ...rest },
  ref,
) {
  return (
    <span ref={ref} className={cx('ard-concept-tag', className)} {...rest}>
      <span className="font-mono">{code}</span>
      {label ? <span className="font-sans text-ink-500">{label}</span> : null}
    </span>
  );
});
