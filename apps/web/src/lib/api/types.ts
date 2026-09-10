/**
 * The API contract, as the API itself declares it.
 *
 * Every shape that crosses the wire is GENERATED from
 * `apps/api/alppy/schemas/__init__.py` by `scripts/generate-api-types.py`, and
 * re-exported here so the 43 modules that import `@/lib/api/types` keep their
 * import path. CI regenerates and diffs, so a renamed or retyped Pydantic
 * field now fails the build instead of the browser.
 *
 * This file used to be a 1 162-line hand mirror of that document. It compiled
 * either way, which is what made it dangerous: four models had drifted to a
 * different NAME on this side (`MasteryCell` was mirrored as `MasteryCellOut`,
 * and likewise `MasteryPoint`, `SheetTaken`, `SheetStudentMastery`), and
 * nothing could have told us whether the shapes underneath had drifted too.
 *
 * What is left below is what the OpenAPI document genuinely does not carry,
 * each with the reason it is absent rather than forgotten.
 */
export type * from '@alppy/shared/api-types';

import type {
  AdaptiveStudentPlan,
  EventKind,
  ExerciseOut,
  ExerciseType,
  JobStatus,
  Uuid,
} from '@alppy/shared/api-types';

/* ------------------------------------------------------------------------
 * Not in the document: the error envelope is RAISED, never returned through
 * a `response_model`, so FastAPI has never heard of it. Hand-written against
 * `api/errors.py`, which is the only thing that can change it.
 * --------------------------------------------------------------------- */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    request_id: string | null;
  };
}

/* ------------------------------------------------------------------------
 * Not in the document: Pydantic `Literal` aliases and `dict[str, str]`, which
 * OpenAPI inlines into every field that uses them rather than giving them a
 * name in `components.schemas`. Named here because the screens pass them
 * around as values — a band key is a prop, not an inline union.
 * --------------------------------------------------------------------- */
export type ApiLocale = 'fr' | 'de' | 'en';
export type LocalisedText = Record<string, string>;
export type MasteryBandKey = 'solid' | 'ok' | 'weak' | 'fading' | 'none';

/** Which evidence chose a plan's competencies. `diagnostic` means there was
 *  none at all and the sheet is a probe, not a diagnosis. */
export type TargetingBasis = 'source_sheet' | 'mastery' | 'diagnostic';

export type AdaptiveFailureReason =
  | 'provider_error'
  | 'unparsable_response'
  | 'pii_gate'
  | 'incomplete';

/** The number of ruled lines in a written-answer box. A plain number on the
 *  wire; named here because the sheet builder passes it through three
 *  components and `number` says nothing at a call site. */
export type AnswerBoxLines = number;

/** How the roster is ordered in the matrix. A *query parameter*, so it earns
 *  no schema of its own. */
export type MatrixSort = 'roster' | 'weakest';

/* ------------------------------------------------------------------------
 * Not in the document: query strings. FastAPI declares these as individual
 * parameters, not as a model, so there is nothing for the generator to name.
 * Bundled here because the client sends them as one object.
 * --------------------------------------------------------------------- */
export interface ExerciseQuery {
  section_id?: Uuid;
  /**
   * A Theme, or the literal `'none'` for exercises the book left untagged.
   * The sentinel is what keeps ExercisePicker's "nothing is unreachable"
   * promise true now that Theme is the builder's root: absence of the
   * parameter means "no theme filter", `'none'` means "the untagged ones".
   */
  chapter_id?: Uuid | 'none';
  type?: ExerciseType;
  difficulty?: number;
  q?: string;
  offset?: number;
  limit?: number;
}

export interface TimelineQuery {
  kind?: EventKind[];
  subject_id?: Uuid;
  since?: string;
  until?: string;
  q?: string;
  offset?: number;
  limit?: number;
}

/* ------------------------------------------------------------------------
 * Not in the document: Python `@property` members. They are computed on the
 * model, so they are not Pydantic fields and not in the JSON either. Derived
 * here instead, from the fields that ARE sent.
 * --------------------------------------------------------------------- */

/** Mirrors `ExerciseOut.is_ai_generated`, which is a property and not serialised. */
export function isAiGenerated(exercise: ExerciseOut): boolean {
  return exercise.origin === 'ai_generated';
}

/** Mirrors `AdaptiveStudentPlan.total_items`, a property and not serialised. */
export function planItemCount(plan: AdaptiveStudentPlan): number {
  return plan.retrieved.length + plan.generated.length;
}

/** Whether a job will ever change again. Not a contract shape; a predicate
 *  over one, kept here because every poller needs it. */
export function isTerminal(status: JobStatus): boolean {
  return status === 'succeeded' || status === 'failed';
}
