import * as Dialog from '@radix-ui/react-dialog';
import type { ReactElement, ReactNode } from 'react';
import { cx } from '../lib/cx';
import { IconClose } from '../icons/set';

export interface SheetProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  trigger?: ReactElement;
  /** Required: the slide-over needs an accessible name. */
  title: ReactNode;
  description?: ReactNode;
  /** Accessible name of the close control — the app supplies the string. */
  closeLabel: string;
  /** Which edge it comes from on `md` and up. Below `md` it is always a bottom sheet. */
  side?: 'right' | 'left';
  footer?: ReactNode;
  children?: ReactNode;
  className?: string;
}

/**
 * A slide-over. On a phone it is a BOTTOM SHEET — thumb-reachable, 88dvh tall,
 * with a grab bar; from `md` up it is an edge panel (docs/plan.md §9).
 *
 * The entry animation is expressed as a responsive arbitrary animation so both
 * forms move in the direction they came from. `motion.css` cuts both under
 * reduced motion.
 */
export function Sheet({
  open,
  defaultOpen,
  onOpenChange,
  trigger,
  title,
  description,
  closeLabel,
  side = 'right',
  footer,
  children,
  className,
}: SheetProps) {
  return (
    <Dialog.Root open={open} defaultOpen={defaultOpen} onOpenChange={onOpenChange}>
      {trigger ? <Dialog.Trigger asChild>{trigger}</Dialog.Trigger> : null}
      <Dialog.Portal>
        <Dialog.Overlay className="anim-fade-in fixed inset-0 z-40 bg-ink-900/50" />
        <Dialog.Content
          data-side={side}
          {...(description ? {} : { 'aria-describedby': undefined })}
          className={cx(
            /* phone: bottom sheet */
            'fixed inset-x-0 bottom-0 z-50 flex max-h-[88dvh] flex-col gap-4 rounded-t-xl',
            'bg-surface p-5 shadow-pop',
            'animate-[ard-slide-up_var(--t)_var(--ease-out-soft)]',
            /* md and up: edge panel */
            'md:inset-y-0 md:bottom-auto md:max-h-none md:h-dvh md:w-[26rem] md:rounded-t-none md:p-6',
            side === 'right'
              ? 'md:right-0 md:left-auto md:rounded-l-xl'
              : 'md:left-0 md:right-auto md:rounded-r-xl',
            'md:animate-[ard-slide-in-right_var(--t)_var(--ease-out-soft)]',
            className,
          )}
        >
          {/* Grab bar: a phone affordance, meaningless on desktop. */}
          <span
            aria-hidden="true"
            data-decorative=""
            className="mx-auto -mt-1 h-1 w-10 rounded-pill bg-line-strong md:hidden"
          />

          <div className="flex items-start gap-3">
            <div className="flex-1">
              <Dialog.Title className="font-display text-h2 font-bold text-ink-900">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="mt-1 text-body-s text-ink-700">
                  {description}
                </Dialog.Description>
              ) : null}
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label={closeLabel}
                className="ard-btn -mr-1 -mt-1 aspect-square min-w-11 px-0"
                data-variant="ghost"
              >
                <IconClose size={20} />
              </button>
            </Dialog.Close>
          </div>

          <div className="flex-1 overflow-y-auto text-body text-ink-700">{children}</div>

          {footer ? (
            <div className="flex flex-col-reverse gap-2 pb-[env(safe-area-inset-bottom)] sm:flex-row sm:justify-end">
              {footer}
            </div>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
