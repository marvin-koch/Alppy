import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../../lib/cx';
import type { BandLabels } from '../../lib/mastery';
import type { MasteryValue } from '../../lib/types';
import { ConceptTag } from './ConceptTag';
import { MasteryCell } from './MasteryCell';

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

  return (
    <div
      ref={ref}
      className={cx(
        'w-full max-w-full overflow-x-auto overscroll-x-contain',
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
        <tbody>
          {students.map((student) => {
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
                  {name}
                </th>
                {competencies.map((competency) => {
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
                        showScore={showScores}
                        selected={selectedCellId === cellId}
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
