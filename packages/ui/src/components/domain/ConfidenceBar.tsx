import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { clamp, pct, toPercent } from '../../lib/geometry';
import { IconWarning } from '../../icons/set';

export interface ConfidenceBarProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  /** Detector confidence, 0..1. */
  value: number;
  /** Below this the detection needs a human. Mirrors the pipeline's threshold. */
  threshold?: number;
  /** Accessible name — the app supplies the string. */
  label: string;
  /** Visible caption for the measurement. */
  caption?: ReactNode;
  /**
   * Shown, in words, whenever the value is under the threshold. Required to
   * keep low confidence textually distinct and not merely a shorter red bar.
   */
  lowLabel?: string;
  /** Spoken value; defaults to the percentage numeral. */
  valueText?: string;
  size?: 'sm' | 'md';
}

/**
 * Detection confidence (F2). Low confidence is distinct three ways: a shorter
 * bar, a different colour, and a warning icon with its own words. The
 * threshold marker stays visible at every width so "just under" is readable.
 */
export const ConfidenceBar = forwardRef<HTMLDivElement, ConfidenceBarProps>(function ConfidenceBar(
  { value, threshold = 0.8, label, caption, lowLabel, valueText, size = 'md', className, ...rest },
  ref,
) {
  const ratio = clamp(value);
  const percent = toPercent(ratio);
  const low = ratio < threshold;

  return (
    <div ref={ref} className={cx('flex w-full flex-col gap-1', className)} {...rest}>
      <div className="flex items-center gap-2">
        <div
          role="meter"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-valuetext={valueText}
          className={cx(
            'relative w-full overflow-hidden rounded-pill bg-surface-2 ring-1 ring-line',
            size === 'sm' ? 'h-2' : 'h-3',
          )}
        >
          <div
            className={cx('h-full rounded-pill', low ? 'bg-warn-500' : 'bg-success-500')}
            style={{ width: pct(ratio) }}
          />
          {/* The threshold marker: where the pipeline stops trusting itself. */}
          <span
            aria-hidden="true"
            className="absolute inset-y-0 w-0.5 -translate-x-1/2 bg-ink-500"
            style={{ left: pct(threshold) }}
          />
        </div>
        <span
          data-numeric=""
          className={cx(
            'min-w-10 text-right font-display font-bold tabular-nums',
            size === 'sm' ? 'text-body-s' : 'text-body',
            low ? 'text-warn-600' : 'text-ink-900',
          )}
        >
          {percent}
        </span>
      </div>
      {low && lowLabel ? (
        <p className="flex items-center gap-1.5 text-body-s font-bold text-warn-600">
          <IconWarning size={14} />
          {lowLabel}
        </p>
      ) : null}
      {caption ? <p className="text-body-s text-ink-500">{caption}</p> : null}
    </div>
  );
});
