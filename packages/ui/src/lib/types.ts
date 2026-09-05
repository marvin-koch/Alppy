import type { MasteryBand } from './mastery';

/** Tints available on `.ard-card`. Accent is absent on purpose: see AiBadge. */
export type CardTint = 'default' | 'primary' | 'warm' | 'success' | 'warn' | 'danger';

/**
 * Chip / badge variants. `accent` is deliberately NOT here — the mandarin is
 * reserved for AI-generated exercises and lives only in `AiBadge`.
 */
export type StatusVariant = 'neutral' | 'primary' | 'success' | 'warn' | 'danger' | 'info';

/** One cell of the mastery matrix. */
export interface MasteryValue {
  band: MasteryBand;
  /** 0..1, or null when never assessed. */
  score: number | null;
}
