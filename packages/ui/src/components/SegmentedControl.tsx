import { forwardRef, useRef, type HTMLAttributes, type ReactNode, type Ref } from 'react';
import { cx } from '../lib/cx';
import { mergeRefs } from '../lib/refs';

export interface SegmentedOption<T extends string = string> {
  value: T;
  label: ReactNode;
  /** Decorative — the label carries the meaning. */
  icon?: ReactNode;
  disabled?: boolean;
}

export interface SegmentedControlProps<T extends string = string>
  extends Omit<HTMLAttributes<HTMLDivElement>, 'onChange'> {
  options: Array<SegmentedOption<T>>;
  value: T;
  onValueChange: (value: T) => void;
  /** Accessible name of the group — the app supplies the string. */
  label: string;
  size?: 'sm' | 'md';
  block?: boolean;
}

/**
 * A radiogroup that looks like a switch: two to four exclusive choices
 * (blank / answer key, class / student, week / month). Arrow keys move the
 * selection, as a radiogroup must.
 */
function SegmentedControlInner<T extends string>(
  { options, value, onValueChange, label, size = 'md', block = false, className, ...rest }: SegmentedControlProps<T>,
  ref: Ref<HTMLDivElement>,
) {
  const container = useRef<HTMLDivElement | null>(null);

  const move = (delta: number) => {
    const enabled = options.filter((option) => !option.disabled);
    if (enabled.length === 0) return;
    const currentIndex = enabled.findIndex((option) => option.value === value);
    const nextIndex = (currentIndex + delta + enabled.length) % enabled.length;
    const next = enabled[nextIndex];
    if (!next) return;
    onValueChange(next.value);
    const node = container.current?.querySelector<HTMLButtonElement>(`[data-value="${next.value}"]`);
    node?.focus();
  };

  return (
    <div
      ref={mergeRefs(ref, container)}
      role="radiogroup"
      aria-label={label}
      className={cx(
        'inline-flex gap-1 rounded-md border border-line bg-surface-2 p-1',
        block && 'flex w-full',
        className,
      )}
      onKeyDown={(event) => {
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
          event.preventDefault();
          move(1);
        } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
          event.preventDefault();
          move(-1);
        }
      }}
      {...rest}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            data-value={option.value}
            disabled={option.disabled}
            tabIndex={selected ? 0 : -1}
            onClick={() => onValueChange(option.value)}
            className={cx(
              'inline-flex flex-1 items-center justify-center gap-2 rounded-sm font-display font-semibold whitespace-nowrap',
              size === 'sm' ? 'min-h-9 px-3 text-body-s' : 'min-h-11 px-4 text-body',
              selected ? 'bg-surface text-primary-700 shadow-[0_2px_0_0_var(--c-line)]' : 'text-ink-500 hover:text-ink-900',
              'disabled:cursor-not-allowed disabled:text-ink-300',
            )}
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export const SegmentedControl = forwardRef(SegmentedControlInner) as <T extends string>(
  props: SegmentedControlProps<T> & { ref?: Ref<HTMLDivElement> },
) => ReturnType<typeof SegmentedControlInner>;
