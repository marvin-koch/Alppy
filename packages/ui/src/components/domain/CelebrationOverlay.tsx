import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react';
import { cx } from '../../lib/cx';

export interface CelebrationOverlayProps {
  open: boolean;
  onDismiss: () => void;
  title: ReactNode;
  description?: ReactNode;
  /** The next action — "print the sheets", "see the matrix". */
  action?: ReactNode;
  /** Accessible name of the dismiss control — the app supplies the string. */
  dismissLabel: string;
  /** Confetti count. Decorative: calm mode and reduced motion both remove it. */
  pieces?: number;
  className?: string;
}

/* Four token colours in rotation. Not the mandarin: that is AI, not applause. */
const CONFETTI = ['bg-primary-500', 'bg-success-500', 'bg-info-500', 'bg-warn-500'] as const;

/**
 * The end of a delivery (DESIGN.md §5): the curtain at `--t-celebrate`, then
 * confetti. `motion.css` cuts both under `prefers-reduced-motion` or
 * `data-motion="off"`, and calm mode strips the confetti entirely — the
 * message and the button survive all three, because they carry the meaning.
 */
export function CelebrationOverlay({
  open,
  onDismiss,
  title,
  description,
  action,
  dismissLabel,
  pieces = 14,
  className,
}: CelebrationOverlayProps) {
  const dismissRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return undefined;
    dismissRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onDismiss();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onDismiss]);

  if (!open) return null;

  return (
    <div className={cx('fixed inset-0 z-50 flex items-center justify-center p-4', className)}>
      <div aria-hidden="true" className="anim-curtain absolute inset-0 bg-canvas-warm" />

      <div aria-hidden="true" data-decorative="" className="pointer-events-none absolute inset-0 overflow-hidden">
        {Array.from({ length: pieces }, (_, index) => (
          <span
            key={index}
            className={cx(
              'anim-confetti absolute top-[12%] h-2.5 w-1.5 rounded-sm',
              CONFETTI[index % CONFETTI.length],
            )}
            style={
              {
                left: `${((index + 1) / (pieces + 1)) * 100}%`,
                animationDelay: `${(index % 5) * 60}ms`,
              } as CSSProperties
            }
          />
        ))}
      </div>

      <div
        role="status"
        aria-live="polite"
        className="ard-card anim-pop-in relative flex max-w-md flex-col items-center gap-4 text-center"
        data-tint="warm"
      >
        <h2 className="font-display text-h1 font-bold text-ink-900">{title}</h2>
        {description ? <p className="text-body text-ink-700">{description}</p> : null}
        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:justify-center">
          {action}
          <button ref={dismissRef} type="button" className="ard-btn" data-variant="ghost" onClick={onDismiss}>
            {dismissLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
