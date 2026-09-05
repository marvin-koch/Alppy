import { forwardRef, useId, useRef, type ClipboardEvent, type KeyboardEvent } from 'react';
import { cx } from '../lib/cx';
import { mergeRefs } from '../lib/refs';
import { useFieldContext } from './Field';

export interface CodeInputProps {
  /** Current value; shorter than `length` while it is being typed. */
  value: string;
  onValueChange: (value: string) => void;
  /** Fired once the value reaches `length`. */
  onComplete?: (value: string) => void;
  length?: number;
  /** Accessible name of the group — the app supplies the string. */
  label: string;
  /** Per-box name. Defaults to `${label} ${index + 1}` — a number, not a word. */
  boxLabel?: (index: number, length: number) => string;
  /** Uppercase alphanumeric by default: sheet codes are printed uppercase. */
  transform?: (raw: string) => string;
  disabled?: boolean;
  invalid?: boolean;
  className?: string;
  autoFocus?: boolean;
}

const DEFAULT_TRANSFORM = (raw: string) => raw.toUpperCase().replace(/[^A-Z0-9]/g, '');

/**
 * The sheet / class code, one character per box. Paste fills every box, and
 * Backspace on an empty box steps back — the two things that make this pattern
 * bearable. The boxes are `inputMode="text"` so a phone shows a usable keypad.
 */
export const CodeInput = forwardRef<HTMLInputElement, CodeInputProps>(function CodeInput(
  {
    value,
    onValueChange,
    onComplete,
    length = 6,
    label,
    boxLabel,
    transform = DEFAULT_TRANSFORM,
    disabled = false,
    invalid,
    className,
    autoFocus = false,
  },
  ref,
) {
  const generated = useId();
  const field = useFieldContext();
  const boxes = useRef<Array<HTMLInputElement | null>>([]);
  const isInvalid = invalid ?? field?.invalid ?? false;

  const commit = (next: string) => {
    const clean = transform(next).slice(0, length);
    onValueChange(clean);
    if (clean.length === length) onComplete?.(clean);
    return clean;
  };

  const focusBox = (index: number) => {
    const target = boxes.current[Math.max(0, Math.min(length - 1, index))];
    target?.focus();
    target?.select();
  };

  const handleKeyDown = (index: number) => (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Backspace' && !event.currentTarget.value) {
      event.preventDefault();
      commit(value.slice(0, Math.max(0, index - 1)));
      focusBox(index - 1);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      focusBox(index - 1);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      focusBox(index + 1);
    }
  };

  const handlePaste = (event: ClipboardEvent<HTMLInputElement>) => {
    event.preventDefault();
    const clean = commit(event.clipboardData.getData('text'));
    focusBox(clean.length);
  };

  return (
    <div
      role="group"
      aria-label={label}
      aria-describedby={field?.describedBy}
      className={cx('flex gap-2', className)}
      onPaste={handlePaste}
    >
      {Array.from({ length }, (_, index) => (
        <input
          key={index}
          ref={mergeRefs(index === 0 ? ref : undefined, (node: HTMLInputElement | null) => {
            boxes.current[index] = node;
          })}
          id={`${generated}-${index}`}
          type="text"
          inputMode="text"
          autoComplete="one-time-code"
          autoFocus={autoFocus && index === 0}
          maxLength={1}
          disabled={disabled}
          aria-label={boxLabel ? boxLabel(index, length) : `${label} ${index + 1}`}
          aria-invalid={isInvalid ? true : undefined}
          value={value[index] ?? ''}
          onChange={(event) => {
            const typed = transform(event.currentTarget.value);
            if (!typed) return;
            const next = (value.slice(0, index) + typed + value.slice(index + typed.length)).slice(0, length);
            const clean = commit(next);
            focusBox(index + typed.length);
            if (clean.length === length) event.currentTarget.blur();
          }}
          onKeyDown={handleKeyDown(index)}
          onFocus={(event) => event.currentTarget.select()}
          className="ard-input h-14 w-11 shrink-0 px-0 text-center font-display text-h2 font-bold uppercase sm:w-12"
        />
      ))}
    </div>
  );
});
