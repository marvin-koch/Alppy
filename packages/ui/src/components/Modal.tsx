import * as Dialog from '@radix-ui/react-dialog';
import type { ReactElement, ReactNode } from 'react';
import { cx } from '../lib/cx';
import { useReturnFocus } from '../lib/useReturnFocus';
import { IconClose } from '../icons/set';

export type ModalSize = 'sm' | 'md' | 'lg';

export interface ModalProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Optional trigger; omit when the app drives `open` itself. */
  trigger?: ReactElement;
  /**
   * Required: this IS the dialog's accessible name (Radix wires it through
   * `aria-labelledby`). Name what the dialog IS — never the control that
   * opened it.
   */
  title: ReactNode;
  description?: ReactNode;
  /** Accessible name of the close control — the app supplies the string. */
  closeLabel: string;
  /** Footer actions. Stacked on a phone, right-aligned from `sm` up. */
  footer?: ReactNode;
  children?: ReactNode;
  size?: ModalSize;
  className?: string;
}

const SIZE: Record<ModalSize, string> = {
  sm: 'sm:max-w-md',
  md: 'sm:max-w-lg',
  lg: 'sm:max-w-2xl',
};

/**
 * A modal dialog. Focus trap, Escape and scroll lock come from Radix; the
 * shell, `aria-modal` and the return-focus behaviour are ours. Radius xl
 * (DESIGN.md §4).
 */
export function Modal({
  open,
  defaultOpen,
  onOpenChange,
  trigger,
  title,
  description,
  closeLabel,
  footer,
  children,
  size = 'md',
  className,
}: ModalProps) {
  const returnFocus = useReturnFocus();

  return (
    <Dialog.Root open={open} defaultOpen={defaultOpen} onOpenChange={onOpenChange}>
      {trigger ? <Dialog.Trigger asChild>{trigger}</Dialog.Trigger> : null}
      <Dialog.Portal>
        <Dialog.Overlay className="anim-fade-in fixed inset-0 z-40 bg-ink-900/50" />
        <Dialog.Content
          /* Truthful: Radix traps focus and marks the rest of the page inert. */
          aria-modal="true"
          {...returnFocus}
          {...(description ? {} : { 'aria-describedby': undefined })}
          className={cx(
            'anim-pop-in fixed left-1/2 top-1/2 z-50 flex max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)]',
            '-translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-y-auto rounded-xl',
            'bg-surface p-5 shadow-pop sm:p-6',
            SIZE[size],
            className,
          )}
        >
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

          {children ? <div className="text-body text-ink-700">{children}</div> : null}

          {footer ? (
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">{footer}</div>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
