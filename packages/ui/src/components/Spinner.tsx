import type { SVGAttributes } from 'react';
import { cx } from '../lib/cx';

export interface SpinnerProps extends Omit<SVGAttributes<SVGSVGElement>, 'children'> {
  /** Matches the icon grid: 18 inside a button, 24 or 32 standing alone. */
  size?: number;
}

/**
 * An indeterminate wait.
 *
 * The counterpart to `ProgressRing`, and the distinction is load-bearing: a ring
 * is a **meter** — it reports a level that is known — so drawing one at 0 for a
 * task whose progress nobody is measuring says "nothing has happened yet", which
 * is both wrong and discouraging. Use a ring when there is a fraction to show
 * (a render job reporting progress), and this when there is only "still going".
 *
 * Decorative by default: the surrounding region carries `role="status"` and the
 * words. A spinning shape is not an announcement.
 */
export function Spinner({ size = 18, className, ...rest }: SpinnerProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      aria-hidden="true"
      focusable="false"
      className={cx('animate-spin', className)}
      {...rest}
    >
      <path d="M12 3.4a8.6 8.6 0 1 0 8.6 8.6" />
    </svg>
  );
}
