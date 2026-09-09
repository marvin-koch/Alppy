import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import type { BandLabels } from '../../lib/mastery';
import type { MasteryValue } from '../../lib/types';
import { ConceptTag } from './ConceptTag';
import { Matrix } from './Matrix';
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
  return (
    <Matrix<MatrixStudent, MatrixCompetency>
      ref={ref}
      rows={students}
      columns={competencies}
      caption={caption}
      rowHeaderLabel={studentColumnLabel}
      showCaption={showCaption}
      bleed={bleed}
      surface={surface}
      {...(className !== undefined ? { className } : {})}
      renderColumnHeader={(competency) => (
        <>
          <ConceptTag code={competency.code} />
          <span className="visually-hidden">{competency.label}</span>
        </>
      )}
      renderRowHeader={(student) => {
        const name = formatStudentName(student);
        return renderStudentName ? renderStudentName(student, name) : name;
      }}
      renderCell={(student, competency, _rowIndex, _colIndex, slot) => {
        const value = valueFor(student.id, competency.id) ?? EMPTY;
        const cellId = `${student.id}:${competency.id}`;
        return (
          <MasteryCell
            band={value.band}
            score={value.score}
            studentName={formatStudentName(student)}
            competencyLabel={competency.label}
            bandLabel={bandLabels[value.band]}
            {...(formatLabel ? { formatLabel } : {})}
            showScore={showScores}
            selected={selectedCellId === cellId}
            {...slot}
            onClick={() =>
              onCellSelect?.({ studentId: student.id, competencyId: competency.id, value })
            }
          />
        );
      }}
      {...rest}
    />
  );
});
