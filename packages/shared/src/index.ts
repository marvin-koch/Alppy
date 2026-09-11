/**
 * Values the web app must not re-type by hand.
 *
 * `layout.generated.ts` is written by `scripts/export-layout.py` from
 * `apps/api/alppy/sheets/layout.py`, and CI fails if it is stale. Re-export it
 * here so there is one import path, and so the generated file has at least one
 * consumer — a contract nothing imports is a contract nobody keeps.
 */
export { CLASS_CODE_PATTERN, classCodeRe, SCAN_THRESHOLDS, SHEET_LAYOUT } from './layout.generated';
export type { SheetLayout } from './layout.generated';

/**
 * `api-types.generated.ts` is the same arrangement one layer up: written by
 * `scripts/generate-api-types.py` from `apps/api/alppy/schemas/__init__.py` as
 * FastAPI serialises it, and CI fails if it is stale. It is re-exported both
 * here and on the `@alppy/shared/api-types` subpath — the subpath so
 * `apps/web`'s API layer can take the contract without also taking the print
 * geometry, this barrel so the rule "one import path" still holds.
 */
export type * from './api-types.generated';
