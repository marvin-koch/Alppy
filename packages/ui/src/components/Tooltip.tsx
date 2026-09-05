import * as RadixTooltip from '@radix-ui/react-tooltip';
import type { ReactElement, ReactNode } from 'react';
import { cx } from '../lib/cx';

/** Mount once, near the app root. Radix needs it for shared delay behaviour. */
export const TooltipProvider = RadixTooltip.Provider;

export interface TooltipProps {
  /** The tip. Never the only place the information exists — touch has no hover. */
  content: ReactNode;
  /** The trigger. Must accept a ref: it is cloned with `asChild`. */
  children: ReactElement;
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  delayDuration?: number;
  className?: string;
}

/**
 * Hover/focus tip. The ink background belongs to the toast, so the tip is a
 * raised surface instead (DESIGN.md §6).
 */
export function Tooltip({
  content,
  children,
  side = 'top',
  align = 'center',
  open,
  defaultOpen,
  onOpenChange,
  delayDuration = 200,
  className,
}: TooltipProps) {
  return (
    <RadixTooltip.Root
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
      delayDuration={delayDuration}
    >
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          align={align}
          sideOffset={8}
          collisionPadding={12}
          className={cx(
            'anim-fade-in z-50 max-w-[min(20rem,calc(100vw-2rem))] rounded-md border border-line',
            'bg-surface px-3 py-2 text-body-s text-ink-900 shadow-pop',
            className,
          )}
        >
          {content}
          <RadixTooltip.Arrow className="fill-surface" width={12} height={6} />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}
