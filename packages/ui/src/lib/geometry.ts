/** Clamp to a closed range. Used for every normalised [0,1] coordinate. */
export function clamp(value: number, min = 0, max = 1): number {
  return value < min ? min : value > max ? max : value;
}

/** Format a 0..1 ratio as an integer percentage. No locale dependency. */
export function toPercent(ratio: number): number {
  return Math.round(clamp(ratio) * 100);
}

/** A CSS percentage string for a normalised coordinate — never a pixel value. */
export function pct(ratio: number): string {
  return `${clamp(ratio) * 100}%`;
}
