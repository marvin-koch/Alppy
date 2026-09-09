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

export interface MatrixRowBase {
  id: string;
}

export interface MatrixColumnBase {
  id: string;
}

/** What a cell must spread onto its focusable element for the grid's single
 *  tab stop and arrow navigation to work. */
export interface MatrixCellSlot {
  'data-row': number;
  'data-col': number;
  tabIndex: number;
  onFocus: () => void;
}

export interface MatrixProps<Row extends MatrixRowBase, Column extends MatrixColumnBase>
  extends Omit<HTMLAttributes<HTMLDivElement>, 'onSelect'> {
  rows: Row[];
  columns: Column[];
  renderColumnHeader: (column: Column) => ReactNode;
  renderRowHeader: (row: Row, rowIndex: number) => ReactNode;
  renderCell: (
    row: Row,
    column: Column,
    rowIndex: number,
    colIndex: number,
    slot: MatrixCellSlot,
  ) => ReactNode;
  /** Names the table for assistive tech — the app supplies the string. */
  caption: string;
  /** Header of the sticky first column — the app supplies the string. */
  rowHeaderLabel: string;
  /** Show the caption above the table instead of only to assistive tech. */
  showCaption?: boolean;
  /** Let the scroller bleed to the screen edges on a phone. */
  bleed?: boolean;
  /**
   * What the sticky first column paints itself with. It MUST match whatever is
   * behind the matrix, or the scrolled cells show through: `surface` inside a
   * Card or Panel (the usual case), `canvas` when the table sits on the page.
   */
  surface?: 'surface' | 'canvas';
}

/**
 * The grid shell every matrix in this app shares: sticky first column,
 * horizontal scroll contained to itself, and ONE tab stop with arrow keys.
 *
 * Headless on purpose. It knows how to move a cursor around a table and
 * nothing about what a cell means — which is what lets a mastery band and a
 * points total use the same keyboard behaviour without either borrowing the
 * other's vocabulary. The five-band colour ramp is a calibrated encoding of
 * decayed competency evidence; a raw score is a different measurement, and a
 * shared *cell* would quietly claim they were the same thing. A shared
 * *shell* claims nothing.
 *
 * Below `md` the grid scrolls horizontally **inside its own container**, so
 * the page body never scrolls sideways. The sticky column paints its own
 * background — a transparent sticky cell lets the scrolled cells slide under
 * the names. The scroller carries `data-matrix-scroll` because the responsive
 * spec asserts against it.
 *
 * Keyboard: arrows move between cells, Home/End jump to the ends of a row,
 * Ctrl+Home/End to the corners. 750 tab stops on a class of 30 is not
 * navigation.
 */
function MatrixInner<Row extends MatrixRowBase, Column extends MatrixColumnBase>(
  {
    rows,
    columns,
    renderColumnHeader,
    renderRowHeader,
    renderCell,
    caption,
    rowHeaderLabel,
    showCaption = false,
    bleed = true,
    surface = 'surface',
    className,
    ...rest
  }: MatrixProps<Row, Column>,
  ref: React.ForwardedRef<HTMLDivElement>,
) {
  const stickyBackground = surface === 'canvas' ? 'bg-canvas' : 'bg-surface';
  const gridRef = useRef<HTMLTableSectionElement>(null);
  // Which cell owns the single tab stop. Clamped on render rather than stored
  // as an id, so a filter or a re-sort cannot strand focus on a vanished cell.
  const [cursor, setCursor] = useState<[number, number]>([0, 0]);
  const activeRow = Math.min(cursor[0], Math.max(0, rows.length - 1));
  const activeCol = Math.min(cursor[1], Math.max(0, columns.length - 1));

  const focusCell = useCallback((row: number, col: number) => {
    const cell = gridRef.current?.querySelector<HTMLElement>(
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

      const lastRow = rows.length - 1;
      const lastCol = columns.length - 1;
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
    [columns.length, focusCell, rows.length],
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
              {rowHeaderLabel}
            </th>
            {columns.map((column) => (
              <th key={column.id} scope="col" className="px-1 py-1 text-center align-bottom">
                {renderColumnHeader(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody ref={gridRef} onKeyDown={onGridKeyDown}>
          {rows.map((row, rowIndex) => (
            <tr key={row.id}>
              <th
                scope="row"
                className={cx(
                  'sticky left-0 z-10 min-w-[9rem] max-w-[12rem] truncate py-1 pr-3',
                  'text-body-s font-bold text-ink-900',
                  'shadow-[1px_0_0_0_var(--c-line)]',
                  stickyBackground,
                )}
              >
                {renderRowHeader(row, rowIndex)}
              </th>
              {columns.map((column, colIndex) => (
                <td key={column.id} className="p-0 align-middle">
                  {renderCell(row, column, rowIndex, colIndex, {
                    'data-row': rowIndex,
                    'data-col': colIndex,
                    tabIndex: rowIndex === activeRow && colIndex === activeCol ? 0 : -1,
                    onFocus: () => setCursor([rowIndex, colIndex]),
                  })}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** `forwardRef` erases generics; this cast restores them for callers. */
export const Matrix = forwardRef(MatrixInner) as <
  Row extends MatrixRowBase,
  Column extends MatrixColumnBase,
>(
  props: MatrixProps<Row, Column> & { ref?: React.ForwardedRef<HTMLDivElement> },
) => ReturnType<typeof MatrixInner>;
