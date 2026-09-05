import { forwardRef, type CSSProperties, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { clamp, toPercent } from '../../lib/geometry';
import type { MasteryBand } from '../../lib/mastery';

export interface ProgressRingProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  /** 0..1. Anything outside is clamped rather than drawn wrong. */
  value: number;
  /** Outer box, px. */
  size?: number;
  /** Ring stroke, px on the rendered size. */
  thickness?: number;
  /** Accessible name — the app supplies the string. */
  label: string;
  /** Spoken value, e.g. "62 % · révision dans 2 jours". Defaults to the percentage. */
  valueText?: string;
  /** Centre content. Defaults to the integer percentage numeral (no % sign: the app owns units). */
  centre?: ReactNode;
  /** Caption under the numeral, inside the ring. */
  centreCaption?: ReactNode;
  /** Colour the arc by mastery band instead of the primary. */
  band?: MasteryBand;
  /** Animate the fill on mount (cut by reduced motion). */
  animate?: boolean;
}

const BAND_STROKE: Record<MasteryBand, string> = {
  solid: 'stroke-mastery-solid',
  ok: 'stroke-mastery-ok',
  weak: 'stroke-mastery-weak',
  fading: 'stroke-mastery-fading',
  none: 'stroke-mastery-none',
};

/**
 * The ring (DESIGN.md §6): SVG rotated −90° so 0 starts at twelve o'clock,
 * drawn with `stroke-dashoffset`, centre numeral in Fredoka with tabular
 * figures. `role="meter"` — it reports a level, it is not a progress bar of a
 * task that will finish.
 */
export const ProgressRing = forwardRef<HTMLDivElement, ProgressRingProps>(function ProgressRing(
  {
    value,
    size = 96,
    thickness = 10,
    label,
    valueText,
    centre,
    centreCaption,
    band,
    animate = true,
    className,
    ...rest
  },
  ref,
) {
  const ratio = clamp(value);
  const percent = toPercent(ratio);
  /* Geometry is computed on a 100×100 viewBox and scaled by `size`. */
  const strokeOnGrid = (thickness / size) * 100;
  const radius = 50 - strokeOnGrid / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - ratio);

  const ringStyle = {
    strokeDasharray: circumference,
    strokeDashoffset: offset,
    ['--ring-circumference' as string]: `${circumference}`,
  } as CSSProperties;

  return (
    <div
      ref={ref}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-valuetext={valueText}
      className={cx('relative inline-flex shrink-0 items-center justify-center', className)}
      style={{ width: size, height: size }}
      {...rest}
    >
      <svg viewBox="0 0 100 100" width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          strokeWidth={strokeOnGrid}
          className="stroke-line"
        />
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          strokeWidth={strokeOnGrid}
          strokeLinecap="round"
          style={ringStyle}
          className={cx(band ? BAND_STROKE[band] : 'stroke-primary-500', animate && 'anim-ring-fill')}
        />
      </svg>
      <span className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 text-center">
        <span
          data-numeric=""
          className="font-display font-bold text-ink-900 tabular-nums"
          style={{ fontSize: Math.round(size * 0.28) }}
        >
          {centre ?? percent}
        </span>
        {centreCaption ? (
          <span className="px-2 text-body-s leading-tight text-ink-500">{centreCaption}</span>
        ) : null}
      </span>
    </div>
  );
});
