import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { pct } from '../../lib/geometry';
import { IconCheck, IconEdit, IconMinus, IconWarning } from '../../icons/set';

export type ScanMarkState = 'detected' | 'empty' | 'ambiguous' | 'corrected';

export interface ScanMark {
  id: string;
  /**
   * NORMALISED FIDUCIAL-FRAME COORDINATES, all in [0,1]: `u`/`v` is the
   * top-left of the box, `w`/`h` its size, expressed as fractions of the frame
   * spanned by the four corner fiducials (print.css, `.print-frame`).
   *
   * The detector emits these, and the overlay positions by percentage — never
   * by pixels — so the boxes stay registered at any rendered width, on a phone
   * and on a 27-inch screen alike.
   */
  u: number;
  v: number;
  w: number;
  h: number;
  state: ScanMarkState;
  /** 0..1. Used to mark a box the pipeline is unsure about. */
  confidence?: number;
  /**
   * Accessible name of this mark: item, detected answer, state. The app builds
   * it — the library translates nothing.
   */
  label: string;
}

export interface ScanReviewOverlayProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onSelect'> {
  /** The scanned page, already deskewed and registered by the pipeline. */
  imageSrc: string;
  /** Alt text for the page — the app supplies the string. */
  imageAlt: string;
  marks: ScanMark[];
  selectedId?: string;
  onSelectMark?: (mark: ScanMark) => void;
  /** Accessible name of the group of marks — the app supplies the string. */
  regionLabel: string;
  /** Below this a box is drawn dashed and flagged, whatever its state. */
  lowConfidenceThreshold?: number;
  /** Extra layers (a legend, a magnifier) rendered above the marks. */
  children?: ReactNode;
}

const STATE_STYLE: Record<ScanMarkState, string> = {
  detected: 'border-success-500 bg-success-100/50 text-success-600',
  empty: 'border-line-strong bg-surface/40 text-ink-500',
  ambiguous: 'border-warn-500 bg-warn-100/60 text-warn-600',
  corrected: 'border-info-500 bg-info-100/60 text-info-600',
};

const STATE_GLYPH: Record<ScanMarkState, ReactNode> = {
  detected: <IconCheck size={14} strokeWidth={3} />,
  empty: <IconMinus size={14} strokeWidth={3} />,
  ambiguous: <IconWarning size={14} strokeWidth={2.6} />,
  corrected: <IconEdit size={14} strokeWidth={2.6} />,
};

/**
 * The scan review (F2): the page as it was scanned, with every detected mark
 * laid over it and correctable.
 *
 * Two rules make this work on a phone as well as a desktop:
 *   1. every box is positioned in percentages of the image box, so the overlay
 *      is resolution-independent and never drifts;
 *   2. every box is a real `<button>` with a 44px hit area (docs/plan.md §9)
 *      even when the bubble itself is 6mm across.
 */
export const ScanReviewOverlay = forwardRef<HTMLDivElement, ScanReviewOverlayProps>(
  function ScanReviewOverlay(
    {
      imageSrc,
      imageAlt,
      marks,
      selectedId,
      onSelectMark,
      regionLabel,
      lowConfidenceThreshold = 0.8,
      children,
      className,
      ...rest
    },
    ref,
  ) {
    return (
      <div
        ref={ref}
        className={cx('relative w-full overflow-hidden rounded-lg border border-line bg-surface-2', className)}
        {...rest}
      >
        <img src={imageSrc} alt={imageAlt} className="block h-auto w-full select-none" draggable={false} />

        <div role="group" aria-label={regionLabel} className="absolute inset-0">
          {marks.map((mark) => {
            const selected = mark.id === selectedId;
            const low = (mark.confidence ?? 1) < lowConfidenceThreshold;
            return (
              <button
                key={mark.id}
                type="button"
                aria-label={mark.label}
                aria-pressed={selected}
                data-state={mark.state}
                data-low-confidence={low ? 'true' : undefined}
                onClick={() => onSelectMark?.(mark)}
                className={cx(
                  'absolute flex items-center justify-center rounded-sm border-2',
                  STATE_STYLE[mark.state],
                  low && 'border-dashed',
                  selected && 'shadow-[var(--focus-ring)]',
                )}
                /* Percentages, never pixels: normalised frame coordinates. */
                style={{ left: pct(mark.u), top: pct(mark.v), width: pct(mark.w), height: pct(mark.h) }}
              >
                {/* Keeps the touch target at 44px however small the bubble is. */}
                <span aria-hidden="true" className="absolute left-1/2 top-1/2 h-11 w-11 -translate-x-1/2 -translate-y-1/2" />
                <span aria-hidden="true" className="relative">
                  {STATE_GLYPH[mark.state]}
                </span>
              </button>
            );
          })}
        </div>

        {children}
      </div>
    );
  },
);
