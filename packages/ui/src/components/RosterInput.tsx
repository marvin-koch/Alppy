import { forwardRef, useMemo, type ReactNode, type TextareaHTMLAttributes } from 'react';
import { cx } from '../lib/cx';
import { Textarea } from './Textarea';

export interface ParsedStudent {
  firstName: string;
  lastName: string;
  /** The line it came from, kept so the teacher can see what was misread. */
  raw: string;
}

export interface RosterInputProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'onChange' | 'value'> {
  value: string;
  onValueChange: (value: string) => void;
  /** Called on every keystroke with the parsed roster. */
  onParsedChange?: (students: ParsedStudent[]) => void;
  /**
   * Renders the preview line. The library ships no strings, so the app decides
   * how to say "24 students". Omit it and only the count is shown.
   */
  renderSummary?: (count: number, students: ParsedStudent[]) => ReactNode;
  /** How many parsed names to show under the count. */
  previewCount?: number;
}

/**
 * One student per line. Accepts what a teacher actually pastes out of a
 * spreadsheet:
 *
 *   Nom, Prénom      → lastName, firstName
 *   Prénom<TAB>Nom   → firstName, lastName   (also `;` and `,`-free columns)
 *   Prénom Nom       → first token is the first name, the rest is the family name
 *
 * Blank lines are dropped. Nothing is normalised beyond trimming: a name is
 * the teacher's data, not ours to clean up.
 */
export function parseRoster(text: string): ParsedStudent[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((raw) => {
      if (raw.includes('\t') || raw.includes(';')) {
        const [first = '', ...rest] = raw.split(/[\t;]+/).map((part) => part.trim());
        return { firstName: first, lastName: rest.join(' ').trim(), raw };
      }
      if (raw.includes(',')) {
        const [last = '', first = ''] = raw.split(',').map((part) => part.trim());
        return { firstName: first, lastName: last, raw };
      }
      const parts = raw.split(/\s+/);
      const [first = '', ...rest] = parts;
      return { firstName: first, lastName: rest.join(' '), raw };
    });
}

/** Paste a class list, see immediately how many students were understood. */
export const RosterInput = forwardRef<HTMLTextAreaElement, RosterInputProps>(function RosterInput(
  { value, onValueChange, onParsedChange, renderSummary, previewCount = 3, className, rows = 8, ...rest },
  ref,
) {
  const students = useMemo(() => parseRoster(value), [value]);

  return (
    <div className={cx('flex flex-col gap-2', className)}>
      <Textarea
        ref={ref}
        value={value}
        rows={rows}
        spellCheck={false}
        onChange={(event) => {
          const next = event.currentTarget.value;
          onValueChange(next);
          onParsedChange?.(parseRoster(next));
        }}
        {...rest}
      />
      {/* The count is the whole point: it tells the teacher the paste worked. */}
      <div aria-live="polite" className="flex flex-wrap items-center gap-2 text-body-s text-ink-700">
        <span data-numeric="" className="font-display text-h3 font-bold text-ink-900">
          {students.length}
        </span>
        {renderSummary ? renderSummary(students.length, students) : null}
        {students.slice(0, previewCount).map((student, index) => (
          <span key={`${student.raw}-${index}`} className="ard-concept-tag">
            {student.firstName} {student.lastName}
          </span>
        ))}
        {students.length > previewCount ? (
          <span data-numeric="" className="text-ink-500">
            +{students.length - previewCount}
          </span>
        ) : null}
      </div>
    </div>
  );
});
