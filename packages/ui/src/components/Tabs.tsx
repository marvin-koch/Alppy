import * as RadixTabs from '@radix-ui/react-tabs';
import { forwardRef, type ComponentPropsWithoutRef } from 'react';
import { cx } from '../lib/cx';

export type TabsProps = ComponentPropsWithoutRef<typeof RadixTabs.Root>;
export type TabsListProps = ComponentPropsWithoutRef<typeof RadixTabs.List>;
export type TabsTriggerProps = ComponentPropsWithoutRef<typeof RadixTabs.Trigger>;
export type TabsContentProps = ComponentPropsWithoutRef<typeof RadixTabs.Content>;

/** Roving focus, arrow keys and `aria-selected` come from Radix. */
export const Tabs = forwardRef<HTMLDivElement, TabsProps>(function Tabs({ className, ...rest }, ref) {
  return <RadixTabs.Root ref={ref} className={cx('flex flex-col gap-4', className)} {...rest} />;
});

/** Scrolls horizontally on a phone rather than wrapping into two rows. */
export const TabsList = forwardRef<HTMLDivElement, TabsListProps>(function TabsList(
  { className, ...rest },
  ref,
) {
  return (
    <RadixTabs.List
      ref={ref}
      className={cx(
        'flex gap-1 overflow-x-auto border-b border-line [scrollbar-width:thin]',
        className,
      )}
      {...rest}
    />
  );
});

export const TabsTrigger = forwardRef<HTMLButtonElement, TabsTriggerProps>(function TabsTrigger(
  { className, ...rest },
  ref,
) {
  return (
    <RadixTabs.Trigger
      ref={ref}
      className={cx(
        'inline-flex min-h-11 shrink-0 items-center gap-2 whitespace-nowrap border-b-2 border-transparent',
        'px-4 font-display text-body font-semibold text-ink-500',
        'hover:text-ink-900 data-[state=active]:border-primary-500 data-[state=active]:text-primary-700',
        className,
      )}
      {...rest}
    />
  );
});

export const TabsContent = forwardRef<HTMLDivElement, TabsContentProps>(function TabsContent(
  { className, ...rest },
  ref,
) {
  return <RadixTabs.Content ref={ref} className={cx('anim-fade-in', className)} {...rest} />;
});
