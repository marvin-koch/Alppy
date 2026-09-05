import { forwardRef, type CSSProperties, type HTMLAttributes } from 'react';
import { cx } from '../lib/cx';

export interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  /** Any CSS length, or a number read as px. Geometry only — never colour. */
  width?: string | number;
  height?: string | number;
  radius?: 'sm' | 'md' | 'lg' | 'pill';
  circle?: boolean;
}

const RADIUS: Record<'sm' | 'md' | 'lg' | 'pill', string> = {
  sm: 'rounded-sm',
  md: 'rounded-md',
  lg: 'rounded-lg',
  pill: 'rounded-pill',
};

/**
 * One shimmering block. Always `aria-hidden`: the announcement belongs to the
 * `LoadingState` region that owns it, not to every rectangle.
 */
export const Skeleton = forwardRef<HTMLDivElement, SkeletonProps>(function Skeleton(
  { width, height = '1rem', radius = 'md', circle = false, className, style, ...rest },
  ref,
) {
  const geometry: CSSProperties = {
    ...(width === undefined ? {} : { width: typeof width === 'number' ? `${width}px` : width }),
    ...(height === undefined ? {} : { height: typeof height === 'number' ? `${height}px` : height }),
    ...style,
  };
  return (
    <div
      ref={ref}
      aria-hidden="true"
      className={cx('ard-skeleton anim-shimmer', circle ? 'rounded-pill' : RADIUS[radius], className)}
      style={geometry}
      {...rest}
    />
  );
});
