import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../lib/cx';

export type AvatarSize = 'sm' | 'md' | 'lg';

export interface AvatarProps extends HTMLAttributes<HTMLSpanElement> {
  firstName: string;
  lastName?: string;
  size?: AvatarSize;
  /**
   * Accessible name. Omit when the student's name is already written next to
   * the avatar — the initials are then decorative and not read twice.
   */
  label?: string;
}

const SIZE: Record<AvatarSize, string> = {
  sm: 'h-8 w-8 text-body-s',
  md: 'h-11 w-11 text-body',
  lg: 'h-14 w-14 text-h3',
};

/* Four token tints, chosen deterministically from the name so a student keeps
   the same one everywhere. No accent: the mandarin is not decoration. */
const TINTS = [
  'bg-primary-100 text-primary-700',
  'bg-info-100 text-info-600',
  'bg-success-100 text-success-600',
  'bg-warn-100 text-warn-600',
] as const;

function initials(first: string, last?: string): string {
  const a = first.trim().charAt(0);
  const b = (last ?? '').trim().charAt(0);
  return (a + b).toUpperCase() || a.toUpperCase();
}

function tintFor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  return TINTS[hash % TINTS.length] ?? TINTS[0];
}

/** Initials in a circle. Never the only identifier — the name is written too. */
export const Avatar = forwardRef<HTMLSpanElement, AvatarProps>(function Avatar(
  { firstName, lastName, size = 'md', label, className, ...rest },
  ref,
) {
  const named = typeof label === 'string' && label.length > 0;
  return (
    <span
      ref={ref}
      role={named ? 'img' : undefined}
      aria-label={named ? label : undefined}
      aria-hidden={named ? undefined : true}
      className={cx(
        'inline-flex shrink-0 select-none items-center justify-center rounded-pill font-display font-bold',
        SIZE[size],
        tintFor(`${firstName} ${lastName ?? ''}`),
        className,
      )}
      {...rest}
    >
      {initials(firstName, lastName)}
    </span>
  );
});
