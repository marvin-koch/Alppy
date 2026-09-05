import { forwardRef, type InputHTMLAttributes } from 'react';
import { cx } from '../lib/cx';
import { useFieldControl } from './Field';

export interface SliderProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'value' | 'onChange'> {
  value: number;
  onValueChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  /**
   * Renders the current value and feeds `aria-valuetext`. The app owns the
   * formatting — number formats are locale-dependent and this library is not.
   */
  formatValue?: (value: number) => string;
  showValue?: boolean;
}

/**
 * The native range input: real keyboard support (arrows, Home/End, PageUp) and
 * the platform's own touch handling. The track takes its colour from the
 * `accent-*` utility, so it follows the theme without a single literal.
 */
export const Slider = forwardRef<HTMLInputElement, SliderProps>(function Slider(
  { value, onValueChange, min = 0, max = 100, step = 1, formatValue, showValue = true, className, id, ...rest },
  ref,
) {
  const aria = useFieldControl({ id, describedBy: rest['aria-describedby'] });
  const text = formatValue?.(value);
  return (
    <div className={cx('flex items-center gap-3', className)}>
      <input
        ref={ref}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onValueChange(Number(event.currentTarget.value))}
        aria-valuetext={text}
        {...rest}
        {...aria}
        className="h-11 w-full cursor-pointer accent-primary-500"
      />
      {showValue ? (
        <output data-numeric="" className="min-w-12 text-right font-display text-body font-semibold text-ink-900">
          {text ?? value}
        </output>
      ) : null}
    </div>
  );
});
