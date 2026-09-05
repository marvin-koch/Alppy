import { forwardRef, type SelectHTMLAttributes } from 'react';
import { cx } from '../lib/cx';
import { IconChevronDown } from '../icons/set';
import { useFieldControl } from './Field';

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  invalid?: boolean;
}

/**
 * The native select on purpose: on a phone it opens the platform picker, which
 * beats any custom listbox for a teacher standing in a classroom.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { invalid, className, id, required, children, ...rest },
  ref,
) {
  const aria = useFieldControl({ id, describedBy: rest['aria-describedby'], invalid, required });
  return (
    <span className={cx('relative block', className)}>
      <select ref={ref} {...rest} {...aria} className="ard-input appearance-none pr-11">
        {children}
      </select>
      <IconChevronDown
        size={18}
        className="pointer-events-none absolute inset-y-0 right-3 my-auto text-ink-500"
      />
    </span>
  );
});
