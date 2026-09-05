import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from '../lib/cx';
import { Skeleton } from './Skeleton';

/**
 * The shape of the page that is arriving. A lone spinner says nothing about
 * what is coming (DESIGN.md §6) — the skeleton is a promise about the layout.
 */
export type LoadingShape = 'matrix' | 'list' | 'sheet' | 'cards' | 'profile';

export interface LoadingStateProps extends HTMLAttributes<HTMLDivElement> {
  shape: LoadingShape;
  /** Announced by the live region — the app supplies the string. */
  label: string;
  /** Rows / cards to draw. Match the real page so nothing jumps on arrival. */
  rows?: number;
  /** Columns, for `matrix` only. */
  columns?: number;
}

export const LoadingState = forwardRef<HTMLDivElement, LoadingStateProps>(function LoadingState(
  { shape, label, rows = 6, columns = 6, className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={cx('w-full', className)}
      {...rest}
    >
      <span className="visually-hidden">{label}</span>
      {shape === 'matrix' ? <MatrixShape rows={rows} columns={columns} /> : null}
      {shape === 'list' ? <ListShape rows={rows} /> : null}
      {shape === 'sheet' ? <SheetShape /> : null}
      {shape === 'cards' ? <CardsShape rows={rows} /> : null}
      {shape === 'profile' ? <ProfileShape /> : null}
    </div>
  );
});

/* students × competencies, with the sticky name column the real matrix has */
function MatrixShape({ rows, columns }: { rows: number; columns: number }) {
  return (
    <div className="overflow-hidden">
      <div className="flex gap-2 pb-2">
        <Skeleton width="9rem" height="1.25rem" className="shrink-0" />
        {Array.from({ length: columns }, (_, c) => (
          <Skeleton key={`h${c}`} width="3rem" height="1.25rem" className="shrink-0" />
        ))}
      </div>
      <div className="flex flex-col gap-2">
        {Array.from({ length: rows }, (_, r) => (
          <div key={`r${r}`} className="flex gap-2">
            <Skeleton width="9rem" height="2.5rem" className="shrink-0" />
            {Array.from({ length: columns }, (_, c) => (
              <Skeleton key={`c${r}-${c}`} width="3rem" height="2.5rem" radius="sm" className="shrink-0" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/* a roster: avatar + name + meta, one row per student */
function ListShape({ rows }: { rows: number }) {
  return (
    <ul className="flex flex-col gap-3">
      {Array.from({ length: rows }, (_, r) => (
        <li key={r} className="flex items-center gap-3">
          <Skeleton width={44} height={44} circle />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton width="45%" height="0.9rem" />
            <Skeleton width="25%" height="0.75rem" />
          </div>
          <Skeleton width="4.5rem" height="1.75rem" radius="pill" />
        </li>
      ))}
    </ul>
  );
}

/* an A4 page: the print preview arriving */
function SheetShape() {
  return (
    <div className="mx-auto flex w-full max-w-[46rem] flex-col gap-4 rounded-lg border border-line bg-surface p-6">
      <div className="flex items-start justify-between gap-4">
        <Skeleton width="55%" height="1.5rem" />
        <Skeleton width="4rem" height="4rem" radius="sm" />
      </div>
      <Skeleton width="30%" height="0.9rem" />
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className="flex flex-col gap-2 pt-2">
          <Skeleton width="80%" height="1rem" />
          <Skeleton width="60%" height="0.85rem" />
          <Skeleton width="40%" height="0.85rem" />
        </div>
      ))}
    </div>
  );
}

/* a grid of cards: classes on the home screen, proposals in the builder */
function CardsShape({ rows }: { rows: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5">
          <Skeleton width="60%" height="1.25rem" />
          <Skeleton width="90%" height="0.85rem" />
          <Skeleton width="70%" height="0.85rem" />
          <div className="flex gap-2 pt-2">
            <Skeleton width="4.5rem" height="1.75rem" radius="pill" />
            <Skeleton width="3.5rem" height="1.75rem" radius="pill" />
          </div>
        </div>
      ))}
    </div>
  );
}

/* one student: rings, then the curve, then history */
function ProfileShape() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-4">
        <Skeleton width={72} height={72} circle />
        <div className="flex flex-col gap-2">
          <Skeleton width="12rem" height="1.5rem" />
          <Skeleton width="7rem" height="0.85rem" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} height="6rem" radius="lg" />
        ))}
      </div>
      <Skeleton height="10rem" radius="lg" />
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} height="2.25rem" />
        ))}
      </div>
    </div>
  );
}
