import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { Matrix } from './Matrix';
import { PointsCell, type PointsCellLabelParts } from './PointsCell';

export interface PointsMatrixStudent {
  id: string;
  firstName: string;
  lastName: string;
}

export interface PointsMatrixColumn {
  id: string;
  /** What the column is: a sheet's title, or the running total. */
  label: string;
  /** Short form for the header, when the title is long. */
  shortLabel?: string;
}

export interface PointsValue {
  /** null = not graded yet. Never rendered as a zero. */
  earned: number | null;
  possible: number;
}

export interface PointsMatrixProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onSelect'> {
  students: PointsMatrixStudent[];
  /** One per sheet, plus optionally a synthetic total column. */
  columns: PointsMatrixColumn[];
  valueFor: (studentId: string, columnId: string) => PointsValue | undefined;
  /** Which column is the running total, drawn as a summary rather than a sheet. */
  totalColumnId?: string;
  caption: string;
  studentColumnLabel: string;
  formatStudentName?: (student: PointsMatrixStudent) => string;
  formatLabel: (parts: PointsCellLabelParts) => string;
  renderStudentName?: (student: PointsMatrixStudent, name: string) => ReactNode;
  selectedCellId?: string;
  onCellSelect?: (selection: {
    studentId: string;
    columnId: string;
    value: PointsValue;
  }) => void;
  bleed?: boolean;
  surface?: 'surface' | 'canvas';
}

const EMPTY: PointsValue = { earned: null, possible: 0 };

/**
 * Students × sheets, in points.
 *
 * Shares the grid shell with the mastery matrix — the sticky column, the single
 * tab stop, the contained horizontal scroll — and shares none of its vocabulary.
 * See `PointsCell` for why the band ramp must not travel with it.
 */
export const PointsMatrix = forwardRef<HTMLDivElement, PointsMatrixProps>(function PointsMatrix(
  {
    students,
    columns,
    valueFor,
    totalColumnId,
    caption,
    studentColumnLabel,
    formatStudentName = (student) => `${student.firstName} ${student.lastName}`.trim(),
    formatLabel,
    renderStudentName,
    selectedCellId,
    onCellSelect,
    bleed = true,
    surface = 'surface',
    className,
    ...rest
  },
  ref,
) {
  return (
    <Matrix<PointsMatrixStudent, PointsMatrixColumn>
      ref={ref}
      rows={students}
      columns={columns}
      caption={caption}
      rowHeaderLabel={studentColumnLabel}
      bleed={bleed}
      surface={surface}
      {...(className !== undefined ? { className } : {})}
      renderColumnHeader={(column) => (
        <span
          className="block max-w-[8rem] truncate text-label uppercase text-ink-500"
          title={column.label}
        >
          {column.shortLabel ?? column.label}
        </span>
      )}
      renderRowHeader={(student) => {
        const name = formatStudentName(student);
        return renderStudentName ? renderStudentName(student, name) : name;
      }}
      renderCell={(student, column, _rowIndex, _colIndex, slot) => {
        const value = valueFor(student.id, column.id) ?? EMPTY;
        const cellId = `${student.id}:${column.id}`;
        return (
          <PointsCell
            earned={value.earned}
            possible={value.possible}
            studentName={formatStudentName(student)}
            columnLabel={column.label}
            formatLabel={formatLabel}
            emphasized={column.id === totalColumnId}
            selected={selectedCellId === cellId}
            {...slot}
            onClick={() => onCellSelect?.({ studentId: student.id, columnId: column.id, value })}
          />
        );
      }}
      {...rest}
    />
  );
});
