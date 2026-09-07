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
export type ExerciseOrigin = 'textbook' | 'ai_generated';
export type SheetTarget = 'class' | 'student' | 'group';
export type SheetKind = 'blank' | 'answer_key';
export type MasteryBandKey = 'solid' | 'ok' | 'weak' | 'fading' | 'none';
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed';
export type JobKind = 'ingest_source' | 'render_sheet' | 'process_scan' | 'generate_adaptive';
export type ScanStatus = 'uploaded' | 'processing' | 'needs_review' | 'confirmed' | 'failed';
export type DetectionOutcome =
  | 'detected'
  | 'low_confidence'
  | 'blank'
  | 'multiple'
  | 'corrected'
  | 'not_gradeable';

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
  school_id: Uuid;
  preferences: TeacherPreferences;
}

/* ----------------------------------------------------------- classes --- */
export interface StudentOut {
  id: Uuid;
  uid: string;
  number: number;
  first_name: string;
  last_name: string;
}

export interface StudentCreate {
  first_name: string;
  last_name: string;
  number?: number | null;
}

export interface RosterCreate {
  students: StudentCreate[];
}

export interface ClassOut {
  id: Uuid;
  code: string;
  label: string | null;
  student_count: number;
  subject_ids: Uuid[];
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
}

/* ------------------------------------------------------------ sources -- */
export interface SourceOut {
  id: Uuid;
  filename: string;
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
  created_at: IsoDateTime;
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
  source_page: number | null;
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
  explanation?: string;
  difficulty?: number;
  approved?: boolean;
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

export interface SheetItemIn {
  exercise_id: Uuid;
  position: number;
  statement_override?: string | null;
}

export interface SheetCreate {
  class_id: Uuid;
  subject_id: Uuid;
  title: string;
  language: ApiLocale;
  target: SheetTarget;
  intent?: string | null;
  items: SheetItemIn[];
}

export interface SheetUpdate {
  title?: string;
  items?: SheetItemIn[];
}

export interface SheetItemOut {
  id: Uuid;
  position: number;
  statement_override: string | null;
  exercise: ExerciseOut;
}

export interface SheetInstanceOut {
  id: Uuid;
  student_id: Uuid;
  student_uid: string;
  page_count: number | null;
}

export interface SheetOut {
  id: Uuid;
  class_id: Uuid;
  subject_id: Uuid;
  title: string;
  target: SheetTarget;
  language: string;
  intent: string | null;
  layout_version: string;
  items: SheetItemOut[];
  instances: SheetInstanceOut[];
  blank_pdf_url: string | null;
  answer_key_pdf_url: string | null;
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
}

export interface DetectionCorrection {
  detected_index: number | null;
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

export interface SheetTakenOut {
  sheet_id: Uuid;
  title: string;
  answered_at: IsoDateTime;
  attempts_count: number;
  correct_count: number;
  scan_id: Uuid | null;
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
}

export interface AdaptiveStudentPlan {
  student_id: Uuid;
  student_uid: string;
  targeted_competency_ids: Uuid[];
  retrieved: ExerciseProposal[];
  generated: ExerciseProposal[];
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
  plans: AdaptiveStudentPlan[];
  language: string;
  generated_count: number;
  needs_approval: boolean;
  group: AdaptiveGroupPlan | null;
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
