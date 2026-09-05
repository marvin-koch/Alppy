import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../lib/cx';
import type { CardTint } from '../lib/types';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Card tints from the recipe. No accent tint: the mandarin is not decor. */
  tint?: CardTint;
  /** Remove the padding so a flush child (a matrix, a table) can bleed to the edge. */
  flush?: boolean;
}

/**
 * A card is a SEPARATE OBJECT: radius lg, solid edge, shadow (DESIGN.md §6).
 * If what you are building is a subdivision of the surface you are already on,
 * you want `Panel`, not `Card`. Do not put shadows everywhere.
 */
export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { tint = 'default', flush = false, className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      data-tint={tint === 'default' ? undefined : tint}
      className={cx('ard-card', flush && 'overflow-hidden p-0', className)}
      {...rest}
    >
      {children}
    </div>
  );
});
