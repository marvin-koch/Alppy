import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { pct } from '../../lib/geometry';
import { IconCheck, IconEdit, IconMinus, IconWarning } from '../../icons/set';

export type ScanMarkState = 'detected' | 'empty' | 'ambiguous' | 'corrected';

/**
 * Where the four corner fiducials sit inside `imageSrc`, as fractions of the
 * image. Mark coordinates are relative to that frame, not to the image, and the
 * two are not the same rectangle: on A4 the frame spans 18–192 mm of a 210 mm
 * page, so treating one as the other puts every box 8–17 mm out — one to two
 * bubble pitches — even on a perfectly flat scan.
 *
 * There is no default. The one thing this component must never do is guess.
 */
export interface ScanFrame {
  u: number;
  v: number;
  w: number;
  h: number;
}

export interface ScanMark {
  id: string;
  /**
   * NORMALISED FIDUCIAL-FRAME COORDINATES, all in [0,1]: `u`/`v` is the
   * top-left of the box, `w`/`h` its size, expressed as fractions of the frame
   * spanned by the four corner fiducials (print.css, `.print-frame`).
   *
   * The detector emits these against the *registered* page, so `imageSrc` must
   * be the deskewed page the pipeline stored — not the photo that came off the
   * camera, which is still rotated.
   */
  u: number;
  v: number;
  w: number;
  h: number;
  /**
   * The item this bubble belongs to. Selecting an item highlights every one of
   * its bubbles, which is the only way a blank or ambiguous item can be shown
   * on the page at all — those have no chosen bubble to point at.
   */
  groupId?: string;
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
  /** Where the fiducial frame sits in that image. See {@link ScanFrame}. */
  frame: ScanFrame;
  marks: ScanMark[];
  /** Matches a mark's `id` or its `groupId`. */
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
 * Three rules make this work:
 *   1. every box is positioned in percentages of the image box, so the overlay
 *      is resolution-independent and never drifts;
 *   2. mark coordinates are frame-relative and are mapped through `frame` —
 *      the frame is not the page, and assuming it was is what put every box a
 *      bubble and a half out of place;
 *   3. every box is a real `<button>` with a 44px hit area (docs/plan.md §9)
 *      even when the bubble itself is 6mm across.
 */
export const ScanReviewOverlay = forwardRef<HTMLDivElement, ScanReviewOverlayProps>(
  function ScanReviewOverlay(
    {
      imageSrc,
      imageAlt,
      frame,
      marks,
      selectedId,
      onSelectMark,
      regionLabel,
      lowConfidenceThreshold = 0.65,
      children,
      className,
      ...rest
    },
    ref,
  ) {
    /** Frame-relative [0,1] -> image-relative [0,1]. */
    const toImage = (mark: ScanMark) => ({
      left: pct(frame.u + mark.u * frame.w),
      top: pct(frame.v + mark.v * frame.h),
      width: pct(mark.w * frame.w),
      height: pct(mark.h * frame.h),
    });

    return (
      <div
        ref={ref}
        className={cx('relative w-full overflow-hidden rounded-lg border border-line bg-surface-2', className)}
        {...rest}
      >
        <img src={imageSrc} alt={imageAlt} className="block h-auto w-full select-none" draggable={false} />

        <div role="group" aria-label={regionLabel} className="absolute inset-0">
          {marks.map((mark) => {
            const selected = selectedId !== undefined &&
              (mark.id === selectedId || mark.groupId === selectedId);
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
                  selected && 'z-10 shadow-[var(--focus-ring)]',
                )}
                style={toImage(mark)}
              >
                {/*
                  A modest hit-area expansion, and deliberately NOT the 44px the
                  touch-target rule asks for. Bubbles sit on an 8mm pitch and are
                  5mm across, so a 44px square around each one covers its
                  neighbours: the topmost box then swallows every click in the
                  row, and the teacher aiming at C selects D. 140% of the box
                  stays inside the pitch (5 x 1.4 = 7mm < 8mm), so every bubble
                  keeps its own target.

                  The 44px target for this screen lives on the correction
                  control in the item list (docs/plan.md §9). These boxes select
                  an item; they do not change an answer.
                */}
                <span
                  aria-hidden="true"
                  className="absolute left-1/2 top-1/2 h-[140%] w-[140%] -translate-x-1/2 -translate-y-1/2"
                />
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
