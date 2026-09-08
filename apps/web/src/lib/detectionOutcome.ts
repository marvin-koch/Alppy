import type { DetectionOut } from '@/lib/api/types';

/** The badge tint for a detection's outcome. Never colour alone: the badge
 *  always carries the outcome's word beside it. */
export function badgeVariant(outcome: DetectionOut['outcome']) {
  if (outcome === 'detected') return 'success' as const;
  if (outcome === 'corrected') return 'primary' as const;
  if (outcome === 'not_gradeable' || outcome === 'pending') return 'neutral' as const;
  return 'warn' as const;
}
