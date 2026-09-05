import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../../lib/cx';
import { clamp } from '../../lib/geometry';
import { BAND_THRESHOLDS } from '../../lib/mastery';

export interface MasteryPoint {
  /** Any monotonic x: an epoch in ms, a day index, a week number. */
  at: number;
  /** 0..1 */
  score: number;
  /** Drawn dashed — the decay model's projection, not an observation. */
  projected?: boolean;
}

export interface MasteryCurveProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  points: MasteryPoint[];
  /** Accessible name — the app supplies the string. */
  label: string;
  /** Longer spoken summary, e.g. "de 0.82 à 0.61 en trois semaines". */
  description?: string;
  height?: number;
  /** Draw the three band thresholds as guides. */
  showThresholds?: boolean;
}

const W = 320;
const PAD_X = 6;
const PAD_Y = 8;

/**
 * The forgetting-style curve (DESIGN.md §6, docs/plan.md §6): mastery decaying
 * between attempts, redrawn upward by each new one. Inline SVG — no chart
 * library, no runtime dependency, and it prints.
 *
 * `preserveAspectRatio` is left at its default so the stroke never distorts;
 * the box scales with its container.
 */
export const MasteryCurve = forwardRef<HTMLDivElement, MasteryCurveProps>(function MasteryCurve(
  { points, label, description, height = 120, showThresholds = true, className, ...rest },
  ref,
) {
  const H = height;
  const sorted = [...points].sort((a, b) => a.at - b.at);
  const xs = sorted.map((p) => p.at);
  const minX = xs.length > 0 ? Math.min(...xs) : 0;
  const maxX = xs.length > 0 ? Math.max(...xs) : 1;
  const span = maxX - minX || 1;

  const x = (at: number) => PAD_X + ((at - minX) / span) * (W - PAD_X * 2);
  const y = (score: number) => PAD_Y + (1 - clamp(score)) * (H - PAD_Y * 2);

  const observed = sorted.filter((p) => !p.projected);
  const projected = sorted.filter((p) => p.projected);
  /* The projection must start where the observations stop, or the line breaks. */
  const lastObserved = observed.at(-1);
  const projectedPath = lastObserved && projected.length > 0 ? [lastObserved, ...projected] : projected;

  const toPath = (list: MasteryPoint[]) =>
    list.map((p, index) => `${index === 0 ? 'M' : 'L'}${x(p.at).toFixed(2)} ${y(p.score).toFixed(2)}`).join(' ');

  const areaPath =
    observed.length > 1
      ? `${toPath(observed)} L${x(observed[observed.length - 1]?.at ?? maxX).toFixed(2)} ${(H - PAD_Y).toFixed(2)} L${x(observed[0]?.at ?? minX).toFixed(2)} ${(H - PAD_Y).toFixed(2)} Z`
      : '';

  return (
    <div
      ref={ref}
      role="img"
      aria-label={label}
      {...(description ? { 'aria-description': description } : {})}
      className={cx('w-full', className)}
      {...rest}
    >
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} aria-hidden="true" className="overflow-visible">
        {showThresholds
          ? [BAND_THRESHOLDS.solid, BAND_THRESHOLDS.ok, BAND_THRESHOLDS.weak].map((threshold) => (
              <line
                key={threshold}
                x1={PAD_X}
                x2={W - PAD_X}
                y1={y(threshold)}
                y2={y(threshold)}
                strokeWidth="1"
                strokeDasharray="3 4"
                className="stroke-line"
              />
            ))
          : null}

        {areaPath ? <path d={areaPath} className="fill-primary-100" stroke="none" /> : null}

        {observed.length > 1 ? (
          <path
            d={toPath(observed)}
            fill="none"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="stroke-primary-500"
          />
        ) : null}

        {projectedPath.length > 1 ? (
          <path
            d={toPath(projectedPath)}
            fill="none"
            strokeWidth="2.5"
            strokeDasharray="5 5"
            strokeLinecap="round"
            className="stroke-ink-300"
          />
        ) : null}

        {sorted.map((point) =>
          point.projected ? null : (
            <circle
              key={`${point.at}`}
              cx={x(point.at)}
              cy={y(point.score)}
              r="3.5"
              className="fill-surface stroke-primary-500"
              strokeWidth="2.5"
            />
          ),
        )}
      </svg>
      {description ? <span className="visually-hidden">{description}</span> : null}
    </div>
  );
});
