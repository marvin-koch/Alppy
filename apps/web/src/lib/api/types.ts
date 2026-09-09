/**
 * The API contract, hand-mirrored from `apps/api/alppy/schemas/__init__.py`
 * and `apps/api/alppy/models/enums.py`.
 *
 * Field names are snake_case because that is what FastAPI serialises: the
 * Pydantic models use `populate_by_name`, not an alias generator.
 *
 * Python `@property` members (`ExerciseOut.is_ai_generated`,
 * `AdaptiveStudentPlan.total_items`) are NOT Pydantic fields and therefore do
 * not appear in the JSON. They are derived here instead — see `isAiGenerated`.
 */

/* ------------------------------------------------------------- enums --- */
export type ApiLocale = 'fr' | 'de' | 'en';
export type LocalisedText = Record<string, string>;

export type CurriculumKind = 'LP21' | 'PER';
export type ExerciseType = 'mcq' | 'true_false' | 'open';
/** `teacher` is an exercise written in the sheet builder. It is deliberately
 *  neither of the other two: it has no source page to audit against a book, and
 *  the mandarin accent means "a model wrote this" — see DESIGN.md §1. */
export type ExerciseOrigin = 'textbook' | 'ai_generated' | 'teacher';
export type SheetTarget = 'class' | 'student' | 'group';
export type SheetKind = 'blank' | 'answer_key' | 'feedback';
export type MasteryBandKey = 'solid' | 'ok' | 'weak' | 'fading' | 'none';
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed';
export type JobKind =
  | 'ingest_source'
  | 'extract_section'
  | 'render_sheet'
  | 'process_scan'
  /** Builds the proposal — targeting, retrieval and the model calls that fill
   *  the shortfall. Distinct from `generate_adaptive`, which despite its name
   *  only renders an approved batch to PDF. */
  | 'propose_adaptive'
  | 'generate_adaptive'
  | 'generate_feedback'
  | 'grade_open_answers';
export type ScanStatus = 'uploaded' | 'processing' | 'needs_review' | 'confirmed' | 'failed';
export type DetectionOutcome =
  | 'detected'
  | 'low_confidence'
  | 'blank'
  | 'multiple'
  | 'corrected'
  | 'not_gradeable'
  /** A written answer, cut from the page and waiting for the vision grader. */
  | 'pending';

/** UUIDs and datetimes both arrive as strings over JSON. */
export type Uuid = string;
export type IsoDateTime = string;

/* -------------------------------------------------------------- auth --- */
export interface LoginRequest {
  email: string;
  password: string;
}

export interface TeacherPreferences {
  locale: ApiLocale;
  /** `null` is a real value: "not chosen" is not "light" — it means follow the system. */
  theme: 'light' | 'dark' | null;
  contrast: 'high' | null;
  motion: 'off' | null;
  calm: 'on' | null;
}

export interface TeacherOut {
  id: Uuid;
  email: string;
  first_name: string;
  last_name: string;
  /** The school this SESSION is acting for — not where the account is based. */
  school_id: Uuid;
  /** Every staffroom this teacher works in (D74). One entry is the common case. */
  schools?: SchoolOut[];
  preferences: TeacherPreferences;
}

/* ----------------------------------------------------------- classes --- */
export interface StudentOut {
  id: Uuid;
  uid: string;
  number: number;
  first_name: string;
  last_name: string;
  /** The class that MINTED `uid` and `number`. Exactly one, and the one the
   *  printed identifier comes from — it does not move with enrollment (D69). */
  home_class_code: string;
  /** Every class this pupil sits in, home first. Two entries means a visitor. */
  class_codes: string[];
}

export interface StudentCreate {
  first_name: string;
  last_name: string;
  number?: number | null;
}

export interface RosterCreate {
  students: StudentCreate[];
}

export interface SchoolOut {
  id: Uuid;
  name: string;
  canton: string | null;
  /** Resolved into every chapter at seed time (D56) — shown, never editable. */
  default_curriculum?: CurriculumKind | null;
}

export interface ClassTeacherOut {
  teacher_id: Uuid;
  first_name: string;
  last_name: string;
  /** The Branches THIS teacher takes in THIS class. */
  subject_ids: Uuid[];
  is_head: boolean;
}

export interface ColleagueOut {
  id: Uuid;
  first_name: string;
  last_name: string;
}

export interface ClassOut {
  id: Uuid;
  code: string;
  label: string | null;
  student_count: number;
  /**
   * The Branches the CALLER takes here, in the class's own order (D73).
   * Not what the class studies — a class may study history without you
   * taking it, and the Branch nav must never offer one you cannot open.
   */
  subject_ids: Uuid[];
  /** What the CLASS studies: the superset. Detail route only. */
  declared_subject_ids?: Uuid[];
  head_teacher_id?: Uuid | null;
  is_head?: boolean;
  /** Detail route only — the list route would fan out a query per class. */
  teachers?: ClassTeacherOut[];
}

export interface ClassCreate {
  code: string;
  label?: string | null;
  school_year_id?: Uuid | null;
}

export interface SubjectOut {
  id: Uuid;
  key: string;
  labels: LocalisedText;
}

/* -------------------------------------------------------- curriculum --- */
export interface CompetencyOut {
  id: Uuid;
  curriculum: CurriculumKind;
  code: string;
  parent_id: Uuid | null;
  subject_key: string;
  cycle: number;
  labels: LocalisedText;
  description: LocalisedText;
}

export interface ChapterOut {
  id: Uuid;
  key: string;
  labels: LocalisedText;
  position: number;
  competency_ids: Uuid[];
  /**
   * The single canonical Competence this Theme hangs from in the navigation
   * tree. Null ONLY on the per-subject `unfiled` bucket — which is what keeps
   * that bucket out of the tree and out of every roll-up.
   */
  primary_competency_id: Uuid | null;
}

/* --------------------------------------------------- the curriculum tree -- */
/**
 * A rolled-up band, from `roll_up_mastery`. The SAME five bands as a matrix
 * cell, so a Theme or a Branch needs no second colour vocabulary — render it
 * with the shipped tokens, glyph and written label exactly like a leaf.
 *
 * `score` is a weighted mean of the children's already-decayed scores, so it
 * is NOT `accuracy * recency` at this level, and `days_until_review` is the
 * earliest of the children's rather than a re-derivation. Both are documented
 * in docs/mastery-model.md §6.
 */
export interface TreeMasteryOut {
  score: number;
  band: MasteryBandKey;
  attempts_count: number;
  provisional: boolean;
  /** Assessed children over total — the coverage behind the band. */
  assessed_count: number;
  child_count: number;
  /** The worst band among the assessed children, or null when none were. */
  weakest_band: MasteryBandKey | null;
  days_until_review: number | null;
  last_attempt_at: string | null;
}

export interface TreeThemeOut {
  chapter_id: Uuid;
  key: string;
  labels: LocalisedText;
  position: number;
  sheet_count: number;
  /** Every competency this Theme credits, for grouping a competency list. */
  competency_ids: Uuid[];
  mastery: TreeMasteryOut;
}

export interface TreeCompetenceOut {
  competency_id: Uuid;
  code: string;
  labels: LocalisedText;
  mastery: TreeMasteryOut;
  themes: TreeThemeOut[];
}

export interface TreeBranchOut {
  subject_id: Uuid;
  subject_key: string;
  labels: LocalisedText;
  mastery: TreeMasteryOut;
  competences: TreeCompetenceOut[];
  /** Sheets in the `unfiled` bucket. Never rolled into `mastery` above. */
  unfiled_sheet_count: number;
  /**
   * Exercises in this Branch with no chapter at all — a different thing from
   * `unfiled_sheet_count`. The builder shows this as a counted "Sans thème"
   * bucket so no exercise becomes unreachable behind the Theme filter.
   */
  unfiled_exercise_count: number;
}

export interface ClassTreeOut {
  class_id: Uuid;
  branches: TreeBranchOut[];
  computed_at: string;
}

/* ------------------------------------------------------------ sources -- */
export interface SourceOut {
  id: Uuid;
  /** The Branch this book belongs to. */
  subject_id: Uuid;
  filename: string;
  /** What the teacher calls it; `filename` is what they uploaded. */
  title: string | null;
  content_type: string;
  size_bytes: number;
  language: string | null;
  page_count: number | null;
  status: JobStatus;
  error: string | null;
  /** A caveat on an otherwise successful ingest: extraction skipped for want
   *  of a grounded model, or only the first N chunks scanned. */
  notice: string | null;
  exercise_count: number;
  section_count: number;
  created_at: IsoDateTime;
}

/** One chapter of the document, as the document itself declares it.
 *
 *  Distinct from `ChapterOut`, which is the teacher's curriculum grouping and
 *  which an exercise reaches only by competency inference — so it is allowed to
 *  be null. This one is a fact about the file and always set, which is why the
 *  builder navigates by it first. */
export interface SourceSectionOut {
  id: Uuid;
  title: string;
  label: string | null;
  page_from: number;
  page_to: number;
  position: number;
  exercise_count: number;
  /** Null means indexed and searchable but never read by a model — the state
   *  the builder offers an "extract" button for. */
  extracted_at: IsoDateTime | null;
  extraction_notice: string | null;
}

/* ---------------------------------------------------------- exercises -- */
export interface ExerciseOut {
  id: Uuid;
  type: ExerciseType;
  origin: ExerciseOrigin;
  language: string;
  statement: string;
  options: string[] | null;
  answer_index: number | null;
  answer_bool: boolean | null;
  answer_text: string | null;
  explanation: string | null;
  difficulty: number;
  chapter_id: Uuid | null;
  competency_ids: Uuid[];
  source_id: Uuid | null;
  source_section_id: Uuid | null;
  source_page: number | null;
  /** The book's own code and title ("NO64", "Les quatre multiplications"),
   *  and a picture of the exercise as the page prints it. Null for anything a
   *  model or a teacher wrote. */
  label: string | null;
  title: string | null;
  figure_url: string | null;
  figure_width_mm: number | null;
  figure_height_mm: number | null;
  approved_at: IsoDateTime | null;
}

/** Mirrors `ExerciseOut.is_ai_generated`, which is a property and not serialised. */
export function isAiGenerated(exercise: ExerciseOut): boolean {
  return exercise.origin === 'ai_generated';
}

export interface ExerciseUpdate {
  statement?: string;
  options?: string[];
  answer_index?: number;
  answer_bool?: boolean;
  answer_text?: string;
  explanation?: string;
  difficulty?: number;
  approved?: boolean;
}

/** An exercise the teacher wrote. `type` and the answer fields must agree; the
 *  API refuses the pair rather than coercing it, because a silently dropped
 *  answer is a sheet whose key is blank for that item. */
export interface ExerciseCreate {
  subject_id: Uuid;
  type: ExerciseType;
  language: ApiLocale;
  statement: string;
  options?: string[] | null;
  answer_index?: number | null;
  answer_bool?: boolean | null;
  answer_text?: string | null;
  explanation?: string | null;
  difficulty?: number;
  chapter_id?: Uuid | null;
  competency_ids?: Uuid[];
}

/** Counts for the filter chips, computed with every filter applied EXCEPT the
 *  type — a chip has to report what selecting it would give. */
export interface ExerciseFacets {
  total: number;
  mcq: number;
  true_false: number;
  open: number;
}

export interface ExerciseListOut {
  items: ExerciseOut[];
  total: number;
  offset: number;
  limit: number;
  facets: ExerciseFacets;
}

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

export interface Provenance {
  source_id: Uuid | null;
  source_filename: string | null;
  page: number | null;
  excerpt: string | null;
  similarity: number | null;
  reason: string;
}

export interface ExerciseProposal {
  exercise: ExerciseOut;
  score: number;
  provenance: Provenance;
}

/* ------------------------------------------------------------- sheets -- */
export interface SheetProposeRequest {
  class_id: Uuid;
  subject_id: Uuid;
  chapter_ids: Uuid[];
  intent?: string | null;
  count: number;
  language?: ApiLocale | null;
  difficulty?: number | null;
}

export interface SheetProposeResponse {
  proposals: ExerciseProposal[];
  language: string;
}

/** What is printed inside a written-answer box, under the student's ink. */
export type AnswerBoxFill = 'lined' | 'grid' | 'blank';

/** The heights the paper reserves room for, in 8 mm lines; 0 prints no box. */
/** Height of the written-answer box in 8 mm lines: 0 prints none, any value
 *  up to `SHEET_LAYOUT.answerBox.maxLines` is allowed; the presets are shortcuts. */
export type AnswerBoxLines = number;

export interface SheetItemIn {
  exercise_id: Uuid;
  position: number;
  statement_override?: string | null;
  /** The written-answer box under an open item; ignored on a bubble item. */
  answer_box_lines?: AnswerBoxLines | null;
  answer_box_fill?: AnswerBoxFill | null;
  /** The teacher's expected answer for this printing of an open item. Blank
   *  means the exercise's own answer if it has one, else the grader works the
   *  answer out itself. Ignored on a bubble item. */
  expected_answer?: string | null;
  /** This item's own barème. Null means "use the sheet's default". Unlike the
   *  box and the expected answer, these are NOT ignored on a bubble item: a
   *  point value means something on every exercise type. */
  points_correct?: number | null;
  /** The penalty as a MAGNITUDE — the server applies the sign. */
  points_penalty?: number | null;
}

export interface SheetCreate {
  class_id: Uuid;
  subject_id: Uuid;
  /** The Theme to file it under. Omitted means "not filed yet" — the API
   *  falls back to the subject's `unfiled` bucket rather than guessing. */
  chapter_id?: Uuid | null;
  title: string;
  language: ApiLocale;
  target: SheetTarget;
  intent?: string | null;
  items: SheetItemIn[];
  /** The barème every item falls back to when it sets none of its own. */
  default_points_correct?: number;
  default_points_penalty?: number;
}

export interface SheetUpdate {
  title?: string;
  /** Re-filing a sheet under the right Theme. */
  chapter_id?: Uuid;
  items?: SheetItemIn[];
  default_points_correct?: number;
  default_points_penalty?: number;
}

/** A sheet that has not been saved, rendered so the teacher can see the paper
 *  while still reordering. Nothing is persisted: the alternative was creating a
 *  real draft and PATCHing it on every edit, which rewrites one SheetInstance
 *  per student per keystroke and leaves a junk row behind. */
export interface SheetDraftPreview {
  class_id: Uuid;
  subject_id: Uuid;
  title: string;
  language: ApiLocale;
  items: SheetItemIn[];
  default_points_correct?: number;
  default_points_penalty?: number;
}

/** One student's marks, aggregated. Field names match `SheetInstanceOut`
 *  because they are the same two numbers one level up. */
export interface StudentPointsOut {
  student_id: Uuid;
  /** null when nothing is graded yet. NEVER render this as a zero: a term with
   *  two of five sheets marked is not three failures. */
  points_earned: number | null;
  points_possible: number;
}

export interface ClassSheetPointsOut {
  sheet_id: Uuid;
  sheet_title: string;
  /** Mean of each graded copy's ratio, 0..1; null when no copy is graded. */
  average_ratio: number | null;
  students: StudentPointsOut[];
}

export interface ClassPointsOut {
  class_id: Uuid;
  /** Totals across every sheet in scope. */
  students: StudentPointsOut[];
  sheets: ClassSheetPointsOut[];
}

/** How one printed item read across the class's copies. Names an item, never
 *  a student: twenty bad readings of question 7 is a bad photocopy. */
/** One question, as one student answered it. */
export interface StudentSheetItemOut {
  position: number;
  number: number | null;
  exercise_id: Uuid;
  statement: string;
  exercise_type: ExerciseType;
  ai_generated: boolean;
  options: string[];
  /** Already readable: "B. 2/3", "Vrai", or the transcription. */
  given: string | null;
  given_index: number | null;
  expected: string | null;
  expected_index: number | null;
  outcome: DetectionOutcome | null;
  confidence: number | null;
  /** null = no attempt at all. Not the same as wrong. */
  correct: boolean | null;
  /** null = ungraded. Never rendered as a zero. */
  points_earned: number | null;
  points_possible: number;
  crop_url: string | null;
}

export interface StudentSheetOut {
  student: StudentOut;
  sheet_id: Uuid;
  sheet_title: string;
  scan_id: Uuid | null;
  answered_at: IsoDateTime | null;
  points_earned: number | null;
  points_possible: number;
  items: StudentSheetItemOut[];
}

export interface ItemConfidenceOut {
  sheet_item_id: Uuid | null;
  exercise_id: Uuid | null;
  number: number | null;
  statement: string | null;
  copies_read: number;
  low_confidence: number;
  ambiguous: number;
  corrected: number;
}

export interface SheetConfidenceOut {
  sheet_id: Uuid;
  items: ItemConfidenceOut[];
}

/** What reopening a pile withdrew, and what it put back. */
export interface ScanUnvalidateResponse {
  attempts_removed: number;
  /** Recomputed from an older pile still confirmed. The gap between removed
   *  and rederived is the number of items that now have no grade at all. */
  attempts_rederived: number;
  students_affected: number;
  competencies_updated: number;
}

export interface SheetItemOut {
  id: Uuid;
  position: number;
  statement_override: string | null;
  answer_box_lines: AnswerBoxLines | null;
  answer_box_fill: AnswerBoxFill | null;
  expected_answer: string | null;
  points_correct: number | null;
  points_penalty: number | null;
  exercise: ExerciseOut;
}

export interface SheetInstanceOut {
  id: Uuid;
  student_id: Uuid;
  student_uid: string;
  page_count: number | null;
  /** "Groupe 2 · Fractions équivalentes", printed on this copy. */
  group_label: string | null;
  /** Whether this copy has an approved feedback page in the third document. */
  has_feedback: boolean;
  /** Points earned, floored at zero; null when nothing is graded yet — which
   *  is not the same as zero, and must not be shown as one. */
  points_earned: number | null;
  /** What this copy's own item list is worth in total. */
  points_possible: number;
}

export interface SheetOut {
  id: Uuid;
  class_id: Uuid;
  subject_id: Uuid;
  /** Required: every sheet has a home Theme, even if it is `unfiled`. */
  chapter_id: Uuid;
  title: string;
  target: SheetTarget;
  language: string;
  intent: string | null;
  layout_version: string;
  default_points_correct: number;
  default_points_penalty: number;
  items: SheetItemOut[];
  instances: SheetInstanceOut[];
  blank_pdf_url: string | null;
  answer_key_pdf_url: string | null;
  /** The per-student feedback pages, as their OWN document — never extra pages
   *  inside a copy, which would desynchronise the scan detector's page count. */
  feedback_pdf_url: string | null;
  /** The common sheet whose corrected results produced this one. */
  derived_from_id: Uuid | null;
  /** Every sheet whose corrected results justified this one, principal first.
   *  `derived_from_id` is entry 0 — one fact, two access paths (D70). */
  source_sheet_ids: Uuid[];
  /** The piles photographed against this sheet. There is no `CorrectedSheet`
   *  entity: a corrected sheet IS the confirmed scan plus the attempts it
   *  wrote, so this is the route from a sheet to its corrections. */
  scans: SheetScanOut[];
  /** Derived from the items, never stored: what this sheet actually covers.
   *  Distinct from `chapter_id`, which is the one home Theme (D71). */
  competency_ids: Uuid[];
  chapter_ids: Uuid[];
  rendered_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

/* -------------------------------------------------------------- scans -- */
export interface DetectionOut {
  id: Uuid;
  item_index: number;
  /** The number printed beside the question on the paper. `item_index` restarts
   *  at 0 on every physical page, so it is not what the student sees. */
  number: number | null;
  sheet_item_id: Uuid | null;
  exercise_id: Uuid | null;
  detected_index: number | null;
  detected_bool: boolean | null;
  confidence: number;
  outcome: DetectionOutcome;
  fill_ratios: number[] | null;
  /**
   * The schema types these as `list[dict[str, float]]` without naming the keys,
   * so they are read defensively in `toScanMarks()` rather than assumed.
   */
  bubble_boxes: Array<Record<string, number>> | null;
  corrected_at: IsoDateTime | null;
  /** What the machine read, kept beside the override rather than under it. */
  machine_index: number | null;
  machine_outcome: DetectionOutcome | null;
  machine_confidence: number | null;
  /** The question this reading is a reading of. */
  statement: string | null;
  options: string[] | null;
  /** The glyphs printed beside the bubbles: ABCD, or V/F, R/F, T/F. */
  option_letters: string | null;
  exercise_type: ExerciseType | null;
  ai_generated: boolean;
  /** The correct option, as an index into `option_letters`. */
  answer_index: number | null;
  /** A written answer: the box cut from the page, what was read in it, and
   *  the verdict — current beside machine, as for the bubbles. */
  crop_url: string | null;
  transcription: string | null;
  verdict_correct: boolean | null;
  machine_transcription: string | null;
  machine_verdict_correct: boolean | null;
  vision_model: string | null;
  /** The expected answer of an open item, for the teacher adjudicating it:
   *  the sheet item's, else the exercise's own. */
  answer_text: string | null;
  /** When no expected answer existed, the answer the model worked out and
   *  judged against. Null whenever `answer_text` is set. */
  reference_answer: string | null;
}

/** A bubble correction carries `detected_index`; a written-answer correction
 *  carries a verdict and/or a transcription. `verdict_correct: null` sent
 *  explicitly means "I cannot tell either". */
export interface DetectionCorrection {
  detected_index?: number | null;
  verdict_correct?: boolean | null;
  transcription?: string | null;
}

export interface ScanPageOut {
  id: Uuid;
  page_index: number;
  image_url: string | null;
  registered: boolean;
  detected_uid: string | null;
  uid_confidence: number | null;
  student_id: Uuid | null;
  sheet_instance_id: Uuid | null;
  /** Belongs to a student who is not in this sheet's class. */
  wrong_class: boolean;
  /** Taken out of the pile by the teacher: a cover sheet, a bad photo. */
  discarded: boolean;
  page_in_copy: number | null;
  registration_error: string | null;
  detections: DetectionOut[];
}

export interface ScanPageDiscard {
  discarded: boolean;
}

export interface ScanPageAssign {
  student_id: Uuid;
}

export interface ScanOut {
  id: Uuid;
  sheet_id: Uuid | null;
  original_filename: string;
  status: ScanStatus;
  error: string | null;
  /** Set on upload only: the job to poll for per-page progress. */
  job_id: Uuid | null;
  pages: ScanPageOut[];
  /** The confirmation history, as derived facts rather than a fourth status.
   *  `ScanStatus` deliberately does NOT gain a 'revised' member: every
   *  `status === 'confirmed'` check in the app would otherwise have to know,
   *  and each one missed silently unlocks a signed-off pile (D48). */
  revised: boolean;
  reopened_at: IsoDateTime | null;
  confirmed_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

export interface ScanConfirmResponse {
  attempts_created: number;
  students_affected: number;
  competencies_updated: number;
  /** A re-scan of the same pile corrects the record rather than doubling it. */
  attempts_superseded: number;
  /** Items that produced no attempt: two bubbles filled, or free text. */
  items_skipped: number;
}

/* ------------------------------------------------------------ mastery -- */
export interface MasteryCellOut {
  student_id: Uuid;
  competency_id: Uuid;
  score: number;
  band: MasteryBandKey;
  attempts_count: number;
  provisional: boolean;
  days_until_review: number | null;
  last_attempt_at: IsoDateTime | null;
}

export interface MasteryMatrixOut {
  class_id: Uuid;
  students: StudentOut[];
  competencies: CompetencyOut[];
  cells: MasteryCellOut[];
  computed_at: IsoDateTime;
}

export interface MasteryPointOut {
  at: IsoDateTime;
  score: number;
  band: MasteryBandKey;
}

export interface CompetencyMastery {
  competency: CompetencyOut;
  score: number;
  band: MasteryBandKey;
  attempts_count: number;
  provisional: boolean;
  days_until_review: number | null;
  history: MasteryPointOut[];
}

/** One pile photographed against a sheet, as the sheet lists it. Not
 *  `ScanOut`: that carries every page and detection. */
export interface SheetScanOut {
  id: Uuid;
  status: ScanStatus;
  /** Signed off, reopened, signed off again (D48). */
  revised: boolean;
  confirmed_at: IsoDateTime | null;
  reopened_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

export interface SheetTakenOut {
  sheet_id: Uuid;
  title: string;
  answered_at: IsoDateTime;
  attempts_count: number;
  correct_count: number;
  scan_id: Uuid | null;
  /** The Theme the sheet is FILED under — the teacher's own filing, never one
   *  inferred from the items. Null only for the `unfiled` bucket. */
  chapter_id: Uuid | null;
  /** This pupil's band on this sheet: a roll-up of the sheet's competencies,
   *  never a mean of its items (I-mastery-11). Null when nothing is tagged. */
  mastery: TreeMasteryOut | null;
}

export interface SheetStudentMasteryOut {
  student_id: Uuid;
  mastery: TreeMasteryOut;
}

/** How a class did on one sheet, in the same five bands as everything else. */
export interface SheetMasteryOut {
  sheet_id: Uuid;
  competency_ids: Uuid[];
  students: SheetStudentMasteryOut[];
  overall: TreeMasteryOut;
  computed_at: IsoDateTime;
}

export interface StudentProfileOut {
  student: StudentOut;
  overall_score: number;
  strengths: CompetencyMastery[];
  gaps: CompetencyMastery[];
  all_competencies: CompetencyMastery[];
  sheets_taken: number;
  sheets: SheetTakenOut[];
}

export interface AttemptOut {
  id: Uuid;
  exercise_id: Uuid;
  statement: string;
  origin: ExerciseOrigin;
  correct: boolean;
  difficulty: number;
  answered_at: IsoDateTime;
  sheet_id: Uuid | null;
  sheet_title: string | null;
  scan_id: Uuid | null;
  corrected: boolean;
}

/** The drill-down behind one matrix cell. */
export interface CompetencyAttemptsOut {
  student: StudentOut;
  competency: CompetencyOut;
  score: number;
  band: MasteryBandKey;
  provisional: boolean;
  days_until_review: number | null;
  attempts: AttemptOut[];
}

/** How the roster is ordered in the matrix. */
export type MatrixSort = 'roster' | 'weakest';

/* ----------------------------------------------------------- adaptive -- */
export interface AdaptiveProposeRequest {
  class_id: Uuid;
  subject_id: Uuid;
  student_ids: Uuid[];
  items_per_student: number;
  allow_generation: boolean;
  /**
   * An explicit teacher override, normally omitted. The language of a sheet
   * follows the SOURCE MATERIAL, and the server reads it off the corpus — it is
   * never the UI locale, so this must not be wired to `useLocale()`.
   */
  language?: ApiLocale | null;
  /** One shared sheet for the selection, targeting the union of their gaps. */
  group?: boolean;
  /** How many personalised group sheets to build. 1 is one shared sheet for the
   *  whole class; a value at or above the class size is one sheet per student. */
  n_groups?: number | null;
  /** Ask a model to revise the deterministic partition. Off by default: the
   *  deterministic rule is the one a teacher can state to a parent, and an
   *  invalid or failed model answer falls straight back to it. */
  llm_grouping?: boolean;
  /** The COMMON sheet whose corrected results justify this batch. */
  source_sheet_id?: Uuid | null;
}

/** Which evidence chose a plan's competencies. `diagnostic` means there was
 *  none at all and the sheet is a probe, not a diagnosis. */
export type TargetingBasis = 'source_sheet' | 'mastery' | 'diagnostic';

export interface AdaptiveStudentPlan {
  student_id: Uuid;
  student_uid: string;
  targeted_competency_ids: Uuid[];
  targeting_basis: TargetingBasis;
  /** The source sheet was only partly read back — copies unscanned, answers
   *  blank or ungraded, items tagged to no competency. The plan stands; it is
   *  built on less than it looks. */
  evidence_partial: boolean;
  retrieved: ExerciseProposal[];
  generated: ExerciseProposal[];
  /** Which personalised group this copy belongs to. Absent on the per-student
   *  path. The teacher may change it before exporting, which is why the batch
   *  request carries the plans rather than re-deriving the partition. */
  group_label?: string | null;
  group_index?: number | null;
  feedback_id?: Uuid | null;
}

/** Mirrors `AdaptiveStudentPlan.total_items`, a property and not serialised. */
export function planItemCount(plan: AdaptiveStudentPlan): number {
  return plan.retrieved.length + plan.generated.length;
}

/** Which students in a group a shared item is actually for. */
export interface AdaptiveGroupItem {
  exercise_id: Uuid;
  for_student_uids: string[];
}

export interface AdaptiveGroupPlan {
  /** "Groupe 2 · Fractions équivalentes". */
  label: string;
  index: number;
  student_ids: Uuid[];
  student_uids: string[];
  targeted_competency_ids: Uuid[];
  retrieved: ExerciseProposal[];
  generated: ExerciseProposal[];
  items: AdaptiveGroupItem[];
}

export type AdaptiveFailureReason =
  | 'provider_error'
  | 'unparsable_response'
  | 'pii_gate'
  | 'incomplete';

export interface AdaptiveGenerationFailure {
  student_id: Uuid;
  student_uid: string;
  reason: AdaptiveFailureReason | string;
  requested: number;
  produced: number;
  detail: string | null;
}

export interface AdaptiveProposeResponse {
  /** True when a model's partition was accepted. False covers both "not asked
   *  for" and "asked for and rejected", so the screen can say which rule the
   *  groups on it came from. */
  grouped_by_model: boolean;
  plans: AdaptiveStudentPlan[];
  language: string;
  generated_count: number;
  needs_approval: boolean;
  /** The single-group path. */
  group: AdaptiveGroupPlan | null;
  /** The N-group path: one entry per personalised group, neediest first. */
  groups: AdaptiveGroupPlan[];
  failures: AdaptiveGenerationFailure[];
}

export interface AdaptiveApproveRequest {
  exercise_ids: Uuid[];
}

export interface AdaptiveApproveResponse {
  approved: number;
  exercise_ids: Uuid[];
}

export interface AdaptiveDiscardRequest {
  exercise_ids: Uuid[];
}

export interface AdaptiveDiscardResponse {
  discarded: number;
  exercise_ids: Uuid[];
}

export interface AdaptiveRegenerateRequest {
  exercise_id: Uuid;
}

export interface AdaptiveRegenerateResponse {
  replaced_exercise_id: Uuid;
  proposal: ExerciseProposal;
}

export interface AdaptiveBatchRequest {
  class_id: Uuid;
  subject_id: Uuid;
  title: string;
  language: ApiLocale;
  plans: AdaptiveStudentPlan[];
  /** Stored as `Sheet.derived_from_id` — the lineage that makes a common sheet
   *  and its differentiated children one teaching unit rather than two rows. */
  source_sheet_id?: Uuid | null;
  /** >1 marks the sheet `SheetTarget.GROUP`. */
  group_count?: number | null;
}

/* ------------------------------------------------ misconception notes -- */
/** One student's feedback, as the teacher reviews it before it prints. */
export interface MisconceptionNoteOut {
  id: Uuid;
  student_id: Uuid;
  student_uid: string;
  subject_id: Uuid;
  based_on_sheet_id: Uuid | null;
  language: string;
  notes: string[];
  competency_ids: Uuid[];
  approved_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

export interface FeedbackApproveRequest {
  feedback_ids: Uuid[];
}

export interface FeedbackApproveResponse {
  approved: number;
  feedback_ids: Uuid[];
}

export interface FeedbackDiscardRequest {
  feedback_ids: Uuid[];
}

export interface FeedbackDiscardResponse {
  discarded: number;
  feedback_ids: Uuid[];
}

export interface FeedbackGenerateRequest {
  class_id: Uuid;
  subject_id: Uuid;
  source_sheet_id: Uuid;
  language?: ApiLocale | null;
}

/* ----------------------------------------------------------- timeline -- */
/** What happened. The names are a teacher's verbs, not the schema's. */
export type EventKind =
  | 'source_imported'
  | 'chapter_read'
  | 'sheet_created'
  | 'sheet_rendered'
  | 'sheet_printed'
  | 'scan_uploaded'
  | 'scan_confirmed'
  | 'adaptive_proposed'
  | 'adaptive_exported'
  | 'feedback_written'
  | 'feedback_approved';

export type EventSubject = 'source' | 'sheet' | 'scan' | 'class';

export interface TimelineEventOut {
  id: Uuid;
  kind: EventKind;
  occurred_at: IsoDateTime;
  subject_type: EventSubject;
  subject_id: Uuid;
  title: string;
  class_id: Uuid | null;
  class_code: string | null;
  subject_area_id: Uuid | null;
  detail: Record<string, number | string>;
  /** False once the row the event describes has been deleted. The line still
   *  shows — deleting a sheet does not un-print it — but must not be a link. */
  resolved: boolean;
}

export interface TimelineFacets {
  by_kind: Partial<Record<EventKind, number>>;
}

export interface TimelineOut {
  items: TimelineEventOut[];
  total: number;
  offset: number;
  limit: number;
  facets: TimelineFacets;
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

/* --------------------------------------------------------------- jobs -- */
export interface JobOut {
  id: Uuid;
  kind: JobKind;
  status: JobStatus;
  /** 0..1 */
  progress: number;
  message: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: IsoDateTime;
  finished_at: IsoDateTime | null;
}

export function isTerminal(status: JobStatus): boolean {
  return status === 'succeeded' || status === 'failed';
}

/* --------------------------------------------------------------- home -- */
export interface ClassSummary {
  class_id: Uuid;
  code: string;
  label: string | null;
  student_count: number;
  last_sheet_title: string | null;
  last_sheet_at: IsoDateTime | null;
  pending_scans: number;
  students_needing_attention: number;
  /** Band key -> number of (student × competency) cells in that band. */
  band_counts: Record<string, number>;
}

export interface HomeOut {
  teacher: TeacherOut;
  subjects: SubjectOut[];
  classes: ClassSummary[];
}

export interface HealthOut {
  status: 'ok' | 'degraded';
  version: string;
  database: boolean;
  redis: boolean;
  storage: boolean;
}

/* ------------------------------------------------------ error envelope -- */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    request_id: string | null;
  };
}
