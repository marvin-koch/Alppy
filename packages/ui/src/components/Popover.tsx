import * as RadixPopover from '@radix-ui/react-popover';
import type { ReactElement, ReactNode } from 'react';
import { cx } from '../lib/cx';

export interface PopoverProps {
  /** The trigger. Must accept a ref: it is cloned with `asChild`. */
  trigger: ReactElement;
  children: ReactNode;
  /** Accessible name for the popover surface — the app supplies the string. */
  label: string;
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
}

/**
 * A small interactive surface anchored to its trigger: a filter, a picker, a
 * band legend. Focus management and dismissal come from Radix.
 */
export function Popover({
  trigger,
  children,
  label,
  side = 'bottom',
  align = 'start',
  open,
  defaultOpen,
  onOpenChange,
  className,
}: PopoverProps) {
  return (
    <RadixPopover.Root open={open} defaultOpen={defaultOpen} onOpenChange={onOpenChange}>
      <RadixPopover.Trigger asChild>{trigger}</RadixPopover.Trigger>
      <RadixPopover.Portal>
        <RadixPopover.Content
          aria-label={label}
          side={side}
          align={align}
          sideOffset={8}
          collisionPadding={12}
          className={cx(
            'anim-pop-in z-50 w-[min(22rem,calc(100vw-2rem))] rounded-lg border border-line',
            'bg-surface p-4 text-body text-ink-900 shadow-pop',
            className,
          )}
        >
          {children}
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}
