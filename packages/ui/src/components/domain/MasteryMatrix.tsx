import {
  forwardRef,
  useCallback,
  useRef,
  useState,
  type HTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { cx } from '../../lib/cx';
import type { BandLabels } from '../../lib/mastery';
import type { MasteryValue } from '../../lib/types';
import { ConceptTag } from './ConceptTag';
import { MasteryCell, type MasteryCellLabelParts } from './MasteryCell';

export interface MatrixStudent {
  id: string;
  firstName: string;
  lastName: string;
}

export interface MatrixCompetency {
  id: string;
  /** Official curriculum code — shown as-is, never coloured. */
  code: string;
  /** Plain-language name, read by assistive tech and shown in the tooltip column. */
  label: string;
}

export interface MasteryMatrixProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onSelect'> {
  students: MatrixStudent[];
  competencies: MatrixCompetency[];
  /** Lookup, so the app keeps its own indexing strategy. */
  valueFor: (studentId: string, competencyId: string) => MasteryValue | undefined;
  /** One label per band, in the teacher's language. */
  bandLabels: BandLabels;
  /** Names the table for assistive tech — the app supplies the string. */
  caption: string;
  /** Header of the sticky first column — the app supplies the string. */
  studentColumnLabel: string;
  onCellSelect?: (selection: { studentId: string; competencyId: string; value: MasteryValue }) => void;
  selectedCellId?: string;
  /** `${firstName} ${lastName}` by default; name order is a locale decision. */
  formatStudentName?: (student: MatrixStudent) => string;
  /**
   * Builds each cell's accessible name. Forwarded straight to `MasteryCell`.
   * Without this the app cannot supply a translated sentence, and every cell
   * falls back to the library's punctuation-joined default — which hard-codes
   * a French-spaced " %".
   */
  formatLabel?: (parts: MasteryCellLabelParts) => string;
  /**
   * Wraps the student's name in the roster column. A matrix whose only route to
   * a profile is a coloured cell strands every student in a class that has not
   * been assessed yet — and the name is the affordance a teacher reaches for.
   */
  renderStudentName?: (student: MatrixStudent, name: string) => ReactNode;
  showScores?: boolean;
  /** Show the caption above the table instead of only to assistive tech. */
  showCaption?: boolean;
  /** Let the scroller bleed to the screen edges on a phone. */
  bleed?: boolean;
  /**
   * What the sticky name column paints itself with. It MUST match whatever is
   * behind the matrix, or the scrolled cells show through: `surface` inside a
   * Card or Panel (the usual case), `canvas` when the table sits on the page.
   */
  surface?: 'surface' | 'canvas';
}

const EMPTY: MasteryValue = { band: 'none', score: null };

/**
 * Students × competencies (F3). THE responsive hard case (docs/plan.md §9):
 * below `md` the grid scrolls horizontally **inside its own container** with a
 * sticky student-name column, so the page body never scrolls sideways. The
 * sticky column paints its own background — a transparent sticky cell would
 * let the scrolled cells slide under the names.
 *
 * The scroller carries `data-matrix-scroll` because the responsive spec asserts
 * against it; the attribute existed only in the test, so that test silently
 * skipped and the overflow it guards went unnoticed. `max-w-full` plus
 * `min-w-0` keep the intrinsic width of `min-w-max` from propagating out to the
 * document, which is what pushed the page sideways on a phone.
 *
 * Keyboard: the grid is ONE tab stop. Arrows move between cells, Home/End jump
 * to the ends of a row, and Enter/Space drill down. 750 tab stops on a class of
 * 30 is not navigation.
 */
export const MasteryMatrix = forwardRef<HTMLDivElement, MasteryMatrixProps>(function MasteryMatrix(
  {
    students,
    competencies,
    valueFor,
    bandLabels,
    caption,
    studentColumnLabel,
    onCellSelect,
    selectedCellId,
    formatStudentName = (student) => `${student.firstName} ${student.lastName}`.trim(),
    formatLabel,
    renderStudentName,
    showScores = true,
    showCaption = false,
    bleed = true,
    surface = 'surface',
    className,
    ...rest
  },
  ref,
) {
  const stickyBackground = surface === 'canvas' ? 'bg-canvas' : 'bg-surface';
  const gridRef = useRef<HTMLTableSectionElement>(null);
  // Which cell owns the single tab stop. Clamped on render rather than stored
  // as an id, so a filter or a re-sort cannot strand focus on a vanished cell.
  const [cursor, setCursor] = useState<[number, number]>([0, 0]);
  const activeRow = Math.min(cursor[0], Math.max(0, students.length - 1));
  const activeCol = Math.min(cursor[1], Math.max(0, competencies.length - 1));

  const focusCell = useCallback((row: number, col: number) => {
    const cell = gridRef.current?.querySelector<HTMLButtonElement>(
      `[data-row="${row}"][data-col="${col}"]`,
    );
    cell?.focus();
  }, []);

  const onGridKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTableSectionElement>) => {
      const target = event.target as HTMLElement;
      const row = Number(target.dataset?.['row']);
      const col = Number(target.dataset?.['col']);
      if (Number.isNaN(row) || Number.isNaN(col)) return;

      const lastRow = students.length - 1;
      const lastCol = competencies.length - 1;
      let next: [number, number] | null = null;
      switch (event.key) {
        case 'ArrowRight':
          next = [row, Math.min(lastCol, col + 1)];
          break;
        case 'ArrowLeft':
          next = [row, Math.max(0, col - 1)];
          break;
        case 'ArrowDown':
          next = [Math.min(lastRow, row + 1), col];
          break;
        case 'ArrowUp':
          next = [Math.max(0, row - 1), col];
          break;
        case 'Home':
          next = event.ctrlKey ? [0, 0] : [row, 0];
          break;
        case 'End':
          next = event.ctrlKey ? [lastRow, lastCol] : [row, lastCol];
          break;
        default:
          return;
      }
      if (next[0] === row && next[1] === col) {
        event.preventDefault();
        return;
      }
      event.preventDefault();
      setCursor(next);
      focusCell(next[0], next[1]);
    },
    [competencies.length, focusCell, students.length],
  );

  return (
    <div
      ref={ref}
      data-matrix-scroll=""
      className={cx(
        'w-full min-w-0 max-w-full overflow-x-auto overscroll-x-contain',
        bleed && '-mx-4 px-4 md:mx-0 md:px-0',
        className,
      )}
      {...rest}
    >
      <table className="min-w-max border-separate border-spacing-1 text-left">
        <caption
          className={cx(
            'text-left text-body-s text-ink-500',
            showCaption ? 'pb-2' : 'visually-hidden',
          )}
        >
          {caption}
        </caption>
        <thead>
          <tr>
            <th
              scope="col"
              className={cx(
                'sticky left-0 z-20 min-w-[9rem] px-2 py-1 text-label uppercase text-ink-500',
                stickyBackground,
              )}
            >
              {studentColumnLabel}
            </th>
            {competencies.map((competency) => (
              <th key={competency.id} scope="col" className="px-1 py-1 text-center align-bottom">
                <ConceptTag code={competency.code} />
                <span className="visually-hidden">{competency.label}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody ref={gridRef} onKeyDown={onGridKeyDown}>
          {students.map((student, rowIndex) => {
            const name = formatStudentName(student);
            return (
              <tr key={student.id}>
                <th
                  scope="row"
                  className={cx(
                    'sticky left-0 z-10 min-w-[9rem] max-w-[12rem] truncate py-1 pr-3',
                    'text-body-s font-bold text-ink-900',
                    'shadow-[1px_0_0_0_var(--c-line)]',
                    stickyBackground,
                  )}
                >
                  {renderStudentName ? renderStudentName(student, name) : name}
                </th>
                {competencies.map((competency, colIndex) => {
                  const value = valueFor(student.id, competency.id) ?? EMPTY;
                  const cellId = `${student.id}:${competency.id}`;
                  return (
                    <td key={competency.id} className="p-0 align-middle">
                      <MasteryCell
                        band={value.band}
                        score={value.score}
                        studentName={name}
                        competencyLabel={competency.label}
                        bandLabel={bandLabels[value.band]}
                        {...(formatLabel ? { formatLabel } : {})}
                        showScore={showScores}
                        selected={selectedCellId === cellId}
                        data-row={rowIndex}
                        data-col={colIndex}
                        tabIndex={rowIndex === activeRow && colIndex === activeCol ? 0 : -1}
                        onFocus={() => setCursor([rowIndex, colIndex])}
                        onClick={() =>
                          onCellSelect?.({ studentId: student.id, competencyId: competency.id, value })
                        }
                      />
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
});
