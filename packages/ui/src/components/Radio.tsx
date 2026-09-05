import {
  createContext,
  forwardRef,
  useContext,
  useId,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from 'react';
import { cx } from '../lib/cx';
import { useFieldContext } from './Field';

interface RadioGroupContextValue {
  name: string;
  value: string | undefined;
  onValueChange: ((value: string) => void) | undefined;
  disabled: boolean;
}

const RadioGroupContext = createContext<RadioGroupContextValue | null>(null);

export interface RadioGroupProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onChange'> {
  /** Shared form name. Generated when omitted. */
  name?: string;
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  disabled?: boolean;
  orientation?: 'vertical' | 'horizontal';
  children: ReactNode;
}

/**
 * A group of native radios. Wrap it in `Field as="fieldset"` so the legend
 * names the group; the browser gives arrow-key navigation for free.
 */
export const RadioGroup = forwardRef<HTMLDivElement, RadioGroupProps>(function RadioGroup(
  { name, value, defaultValue, onValueChange, disabled = false, orientation = 'vertical', className, children, ...rest },
  ref,
) {
  const generated = useId();
  return (
    <RadioGroupContext.Provider
      value={{
        name: name ?? `${generated}-radio-group`,
        value: value ?? defaultValue,
        onValueChange,
        disabled,
      }}
    >
      <div
        ref={ref}
        role="radiogroup"
        aria-orientation={orientation}
        className={cx('flex gap-2', orientation === 'vertical' ? 'flex-col' : 'flex-row flex-wrap', className)}
        {...rest}
      >
        {children}
      </div>
    </RadioGroupContext.Provider>
  );
});

export interface RadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'size'> {
  label: ReactNode;
  description?: ReactNode;
  value: string;
}

export const Radio = forwardRef<HTMLInputElement, RadioProps>(function Radio(
  { label, description, value, className, id, name, checked, onChange, disabled, ...rest },
  ref,
) {
  const group = useContext(RadioGroupContext);
  const field = useFieldContext();
  const generated = useId();
  const inputId = id ?? `${generated}-radio`;
  const descriptionId = description ? `${generated}-description` : undefined;
  const describedBy =
    [rest['aria-describedby'], descriptionId, field?.describedBy].filter(Boolean).join(' ') || undefined;

  return (
    <div className={cx('flex min-h-11 items-start gap-3 py-1.5', className)}>
      <span className="relative mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center">
        <input
          ref={ref}
          id={inputId}
          type="radio"
          value={value}
          name={name ?? group?.name}
          checked={checked ?? (group?.value === undefined ? undefined : group.value === value)}
          disabled={disabled ?? group?.disabled}
          onChange={(event) => {
            onChange?.(event);
            group?.onValueChange?.(value);
          }}
          {...rest}
          aria-describedby={describedBy}
          className={cx(
            'peer absolute inset-0 h-full w-full cursor-pointer appearance-none rounded-pill border-2 bg-surface',
            'border-line-strong transition-colors',
            'checked:border-primary-500 checked:bg-primary-500',
            'disabled:cursor-not-allowed disabled:bg-surface-2',
          )}
        />
        <span
          aria-hidden="true"
          className="pointer-events-none relative h-2 w-2 rounded-pill bg-surface opacity-0 peer-checked:opacity-100"
        />
      </span>
      <label htmlFor={inputId} className="cursor-pointer text-body">
        <span className="block text-ink-900">{label}</span>
        {description ? (
          <span id={descriptionId} className="block text-body-s text-ink-500">
            {description}
          </span>
        ) : null}
      </label>
    </div>
  );
});
