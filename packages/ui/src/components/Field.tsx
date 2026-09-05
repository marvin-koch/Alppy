import {
  createContext,
  forwardRef,
  useContext,
  useId,
  type HTMLAttributes,
  type ReactNode,
  type Ref,
} from 'react';
import { cx } from '../lib/cx';
import { IconWarning } from '../icons/set';

interface FieldContextValue {
  controlId: string;
  describedBy: string | undefined;
  invalid: boolean;
  required: boolean;
}

const FieldContext = createContext<FieldContextValue | null>(null);

export interface FieldProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  /** Visible label. Required: an unlabelled field is not a field. */
  label: ReactNode;
  children: ReactNode;
  /** Persistent help, wired through `aria-describedby`. */
  help?: ReactNode;
  /** Error message. Its presence sets `aria-invalid` on the control. */
  error?: ReactNode;
  required?: boolean;
  /** Screen-reader word for the required marker — the app supplies the string. */
  requiredLabel?: string;
  /** Keeps the label for assistive tech but takes it out of the layout. */
  hideLabel?: boolean;
  /** Use for a group of controls (radios, segmented): renders a fieldset. */
  as?: 'div' | 'fieldset';
  id?: string;
}

/**
 * Label + help + error, wired to the control through `aria-describedby` and
 * `aria-invalid` (DESIGN.md §6: invalid changes the border AND adds a message —
 * never colour alone). Any control below reads the wiring from context, so
 * `<Field label="…"><Input /></Field>` is enough.
 */
export const Field = forwardRef<HTMLDivElement, FieldProps>(function Field(
  {
    label,
    children,
    help,
    error,
    required = false,
    requiredLabel,
    hideLabel = false,
    as = 'div',
    id,
    className,
    ...rest
  },
  ref,
) {
  const generated = useId();
  const controlId = id ?? `${generated}-control`;
  const helpId = `${generated}-help`;
  const errorId = `${generated}-error`;
  const describedBy = [help ? helpId : null, error ? errorId : null].filter(Boolean).join(' ') || undefined;
  const invalid = Boolean(error);

  const labelNode = (
    <>
      {label}
      {required ? (
        <>
          <span aria-hidden="true" className="ml-0.5 text-danger-600">
            *
          </span>
          {requiredLabel ? <span className="visually-hidden"> {requiredLabel}</span> : null}
        </>
      ) : null}
    </>
  );

  const body = (
    <FieldContext.Provider value={{ controlId, describedBy, invalid, required }}>
      {as === 'fieldset' ? (
        <legend className={cx('type-label mb-2 text-ink-700', hideLabel && 'visually-hidden')}>
          {labelNode}
        </legend>
      ) : (
        <label
          htmlFor={controlId}
          className={cx('type-label block text-ink-700', hideLabel && 'visually-hidden')}
        >
          {labelNode}
        </label>
      )}
      {children}
      {help ? (
        <p id={helpId} className="text-body-s text-ink-500">
          {help}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="flex items-start gap-1.5 text-body-s font-bold text-danger-600">
          <IconWarning size={16} className="mt-0.5" />
          <span>{error}</span>
        </p>
      ) : null}
    </FieldContext.Provider>
  );

  if (as === 'fieldset') {
    return (
      <fieldset
        ref={ref as unknown as Ref<HTMLFieldSetElement>}
        className={cx('flex min-w-0 flex-col gap-1.5 border-0 p-0', className)}
        {...(rest as HTMLAttributes<HTMLFieldSetElement>)}
      >
        {body}
      </fieldset>
    );
  }

  return (
    <div ref={ref} className={cx('flex min-w-0 flex-col gap-1.5', className)} {...rest}>
      {body}
    </div>
  );
});

/** The wiring a control inherits from its `Field`, if it has one. */
export function useFieldContext(): FieldContextValue | null {
  return useContext(FieldContext);
}

export interface FieldControlAria {
  id: string | undefined;
  'aria-describedby': string | undefined;
  'aria-invalid': true | undefined;
  required: boolean | undefined;
}

/** Merge a control's own props with the Field's wiring. Explicit props win. */
export function useFieldControl(own: {
  id?: string | undefined;
  describedBy?: string | undefined;
  invalid?: boolean | undefined;
  required?: boolean | undefined;
}): FieldControlAria {
  const field = useFieldContext();
  const describedBy = [own.describedBy, field?.describedBy].filter(Boolean).join(' ') || undefined;
  const invalid = own.invalid ?? field?.invalid ?? false;
  return {
    id: own.id ?? field?.controlId,
    'aria-describedby': describedBy,
    'aria-invalid': invalid ? true : undefined,
    required: own.required ?? field?.required,
  };
}
