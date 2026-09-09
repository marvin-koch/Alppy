import type { ReactNode } from 'react';

import { cx } from '../lib/cx';

export interface SelectSurfaceOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectSurfaceProps {
  /**
   * The accessible name — the WORD, not the current value ("Classe", not
   * "7B"). Visually the face below carries the value; a screen reader gets the
   * name from here and the value from the select itself.
   */
  label: string;
  value: string;
  options: SelectSurfaceOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  /** What the control looks like. Decorative: the select is the control. */
  children: ReactNode;
  className?: string;
}

/**
 * A real `<select>` wearing a face of our own.
 *
 * The rail's scope switcher and the page filters were two stacked boxes with
 * shouty uppercase labels above them, which is a lot of chrome for a control
 * whose whole job is to say one short word. This keeps everything the native
 * element is chosen for — the platform picker on a phone, keyboard operation
 * nobody has to learn, and a real accessible name — and replaces only the
 * appearance: the select is stretched transparently over an arbitrary face.
 *
 * The face is `aria-hidden` on purpose. It repeats the value the select
 * already announces, and a screen reader that read both would say the class
 * code twice.
 */
export function SelectSurface({
  label,
  value,
  options,
  onChange,
  disabled = false,
  children,
  className,
}: SelectSurfaceProps) {
  return (
    <div
      className={cx(
        // No radius of its own: stacked inside a rounded, overflow-hidden
        // container (the rail's scope panel) its corners cut a visible notch
        // out of the divider between rows. The caller sets one when it wants
        // the focus halo rounded.
        'relative isolate transition-shadow',
        // The select on top is transparent, so the ring has to come from the
        // wrapper. Same two-step focus as `.ard-input`: border, then halo.
        'focus-within:shadow-[0_0_0_4px_var(--c-primary-100)]',
        disabled && 'opacity-60',
        className,
      )}
      data-select-surface
    >
      <div aria-hidden>{children}</div>
      <select
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.value)}
        // Covers the face exactly, so the native popup anchors to what the
        // teacher actually clicked rather than to a hidden box elsewhere.
        className="absolute inset-0 h-full w-full cursor-pointer appearance-none opacity-0 disabled:cursor-not-allowed"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
