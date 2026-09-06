/**
 * Values the web app must not re-type by hand.
 *
 * `layout.generated.ts` is written by `scripts/export-layout.py` from
 * `apps/api/alppy/sheets/layout.py`, and CI fails if it is stale. Re-export it
 * here so there is one import path, and so the generated file has at least one
 * consumer — a contract nothing imports is a contract nobody keeps.
 */
export { SHEET_LAYOUT } from './layout.generated';
export type { SheetLayout } from './layout.generated';
