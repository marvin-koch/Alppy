/* AUTO-GENERATED — DO NOT EDIT BY HAND.
 *
 * Source: docs/design/alppy-brand-assets/brand/illustrations/
 * Regenerate: python packages/ui/scripts/generate-illustrations.py
 *
 * 120px, flat, exactly three colours: primary-100 fill, primary-500 stroke,
 * accent-500 for the single point of attention. The flat hexes in the brand
 * export are mapped back onto tokens here so the drawings follow the theme.
 *
 * Every one is decorative: `data-decorative` means calm mode removes it, and
 * `aria-hidden` means a screen reader never announces it. No mascot — that is
 * a deliberate decision, not an omission.
 */

import { Illustration } from './Illustration';
import type { IllustrationProps } from './Illustration';

export function IlloClock(props: IllustrationProps) {
  return (
    <Illustration {...props}>
      <circle cx="60" cy="62" r="40" fill="var(--c-primary-100)" />
      <circle cx="60" cy="62" r="40" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" />
      <path d="M60 38v24l16 11" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M60 14v8M100 62h8M20 62h-8" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" />
      <circle cx="60" cy="62" r="5" fill="var(--c-accent-500)" />
    </Illustration>
  );
}

export function IlloCompass(props: IllustrationProps) {
  return (
    <Illustration {...props}>
      <path d="M60 26 38 90h44z" fill="var(--c-primary-100)" />
      <path d="M60 26 38 90M60 26l22 64" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" />
      <path d="M38 90l-6 8M82 90l6 8" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" />
      <path d="M45 66a30 30 0 0 0 30 0" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" />
      <circle cx="60" cy="24" r="7" fill="var(--c-accent-500)" />
    </Illustration>
  );
}

export function IlloCurve(props: IllustrationProps) {
  return (
    <Illustration {...props}>
      <path d="M24 96V24" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" />
      <path d="M24 96h72" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" />
      <path d="M24 34c26 0 24 62 72 62H24Z" fill="var(--c-primary-100)" />
      <path d="M24 34c26 0 24 62 72 62" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" />
      <circle cx="52" cy="60" r="6" fill="var(--c-primary-500)" />
      <circle cx="96" cy="96" r="7" fill="var(--c-accent-500)" />
    </Illustration>
  );
}

export function IlloSheet(props: IllustrationProps) {
  return (
    <Illustration {...props}>
      <path d="M26 16h44l24 24v64a4 4 0 0 1-4 4H26a4 4 0 0 1-4-4V20a4 4 0 0 1 4-4z" fill="var(--c-primary-100)" />
      <path d="M26 16h44l24 24v64a4 4 0 0 1-4 4H26a4 4 0 0 1-4-4V20a4 4 0 0 1 4-4z" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinejoin="round" />
      <path d="M70 16v20a4 4 0 0 0 4 4h20" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinejoin="round" />
      <path d="M36 58h44M36 74h44M36 90h26" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" />
      <circle cx="76" cy="90" r="6" fill="var(--c-accent-500)" />
    </Illustration>
  );
}

export function IlloSlate(props: IllustrationProps) {
  return (
    <Illustration {...props}>
      <rect x="14" y="20" width="92" height="76" rx="14" fill="var(--c-primary-100)" />
      <rect x="14" y="20" width="92" height="76" rx="14" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" />
      <path d="M38 78 60 36l22 42" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M48 63q12 14 24 0" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" />
      <circle cx="88" cy="32" r="7" fill="var(--c-accent-500)" />
      <path d="M40 104h40" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" />
    </Illustration>
  );
}

export function IlloSummit(props: IllustrationProps) {
  return (
    <Illustration {...props}>
      <path d="M10 98 40 44l16 27 12-18 32 45z" fill="var(--c-primary-100)" />
      <path d="M10 98 40 44l16 27 12-18 32 45z" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinejoin="round" />
      <path d="M28 70h24M74 76h12" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" />
      <path d="M40 44V18" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinecap="round" />
      <path d="M40 20h20l-5 8 5 8H40z" fill="var(--c-accent-500)" />
    </Illustration>
  );
}

export function IlloTray(props: IllustrationProps) {
  return (
    <Illustration {...props}>
      <path d="M22 62h22l6 12h20l6-12h22v34a6 6 0 0 1-6 6H28a6 6 0 0 1-6-6z" fill="var(--c-primary-100)" />
      <path d="M22 62 34 26a6 6 0 0 1 5.7-4h40.6a6 6 0 0 1 5.7 4L98 62v34a6 6 0 0 1-6 6H28a6 6 0 0 1-6-6z" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinejoin="round" />
      <path d="M22 62h22l6 12h20l6-12h22" fill="none" stroke="var(--c-primary-500)" strokeWidth="4.0" strokeLinejoin="round" />
      <circle cx="92" cy="30" r="8" fill="var(--c-accent-500)" />
    </Illustration>
  );
}
