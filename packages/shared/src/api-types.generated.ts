// AUTO-GENERATED — DO NOT EDIT.
// Source of truth: apps/api/alppy/schemas/__init__.py, as FastAPI
// serialises it (create_app().openapi()).
// Regenerate with: PYTHONPATH=apps/api python scripts/generate-api-types.py
// CI fails if this file is stale (see .github/workflows/ci.yml) --
// a renamed or retyped Pydantic field used to compile on both sides
// and fail in the browser, with no test in between.
//
// Field names are snake_case because that is what FastAPI serialises:
// the Pydantic models use `populate_by_name`, not an alias generator.
//
// A property is optional (`?`) only on a schema this API accepts as a
// REQUEST body and never returns, and there exactly when its Pydantic
// field has a default. A returned schema has no optional properties:
// nothing here passes `response_model_exclude_unset`, so a defaulted
// field is always serialised. A schema that is both keeps the
// response reading, because that is the one a screen relies on.
//
// `| null` is unaffected either way -- that is a value on the wire,
// not an absent key.

/** A UUID, as a string. `format: uuid` on the wire. */
export type Uuid = string;

/** An ISO-8601 timestamp, as a string. `format: date-time` on the wire. */
export type IsoDateTime = string;

/** The only way an AI-generated item becomes printable. */
export interface AdaptiveApproveRequest {
  exercise_ids: Uuid[];
}

export interface AdaptiveApproveResponse {
  approved: number;
  exercise_ids: Uuid[];
}

export interface AdaptiveBatchRequest {
  class_id: Uuid;
  subject_id: Uuid;
  title: string;
  language: 'fr' | 'de' | 'en';
  plans: AdaptiveStudentPlan[];
  source_sheet_id?: Uuid | null;
  source_sheet_ids?: Uuid[] | null;
  group_count?: number | null;
}

export interface AdaptiveDiscardRequest {
  exercise_ids: Uuid[];
}

export interface AdaptiveDiscardResponse {
  discarded: number;
  exercise_ids: Uuid[];
}

/**
 * Generation could not fill a student's sheet, and why.
 *
 * A shorter sheet with no explanation is the failure a teacher cannot act on:
 * they count fifteen items where they asked for sixteen and have no way to
 * tell whether the corpus ran out or the provider fell over.
 */
export interface AdaptiveGenerationFailure {
  student_id: Uuid;
  student_uid: string;
  reason: string;
  requested: number;
  produced: number;
  detail: string | null;
}

/** Which students in the group a shared item is actually for. */
export interface AdaptiveGroupItem {
  exercise_id: Uuid;
  for_student_uids: string[];
}

/** One item list shared by several students with overlapping gaps. */
export interface AdaptiveGroupPlan {
  label: string;
  index: number;
  student_ids: Uuid[];
  student_uids: string[];
  targeted_competency_ids: Uuid[];
  retrieved: ExerciseProposal[];
  generated: ExerciseProposal[];
  items: AdaptiveGroupItem[];
}

export interface AdaptiveProposeRequest {
  class_id: Uuid;
  subject_id: Uuid;
  student_ids?: Uuid[];
  items_per_student?: number;
  allow_generation?: boolean;
  language?: 'fr' | 'de' | 'en' | null;
  group?: boolean;
  n_groups?: number | null;
  source_sheet_id?: Uuid | null;
  llm_grouping?: boolean;
}

export interface AdaptiveProposeResponse {
  plans: AdaptiveStudentPlan[];
  grouped_by_model: boolean;
  language: string;
  generated_count: number;
  needs_approval: boolean;
  group: AdaptiveGroupPlan | null;
  groups: AdaptiveGroupPlan[];
  failures: AdaptiveGenerationFailure[];
}

export interface AdaptiveRegenerateRequest {
  exercise_id: Uuid;
}

/** The replacement, plus the id it replaced so the UI can swap in place. */
export interface AdaptiveRegenerateResponse {
  replaced_exercise_id: Uuid;
  proposal: ExerciseProposal;
}

export interface AdaptiveStudentPlan {
  student_id: Uuid;
  student_uid: string;
  targeted_competency_ids: Uuid[];
  targeting_basis: 'source_sheet' | 'mastery' | 'diagnostic';
  evidence_partial: boolean;
  retrieved: ExerciseProposal[];
  generated: ExerciseProposal[];
  group_label: string | null;
  group_index: number | null;
  feedback_id: Uuid | null;
}

/**
 * What is printed inside a written-answer box, under the student's ink.
 *
 * Every fill prints lighter than pen so the crop step can suppress it by
 * luminance; the border and the corner ticks are removed by geometry.
 */
export type AnswerBoxFill = 'lined' | 'grid' | 'blank';

/**
 * One graded item behind a matrix cell, with its provenance.
 *
 * This is the bottom of the drill-down: a teacher who disagrees with a band
 * follows it to the individual answers, and from any answer back to the sheet
 * it was printed on and the scan it was read from.
 */
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

export interface Body_add_scan_pages_api_v1_scans__scan_id__pages_post {
  files: string[];
  supersedes_page_id?: Uuid | null;
}

export interface Body_upload_scan_api_v1_scans_post {
  files: string[];
  sheet_id: Uuid;
}

export interface Body_upload_source_api_v1_sources_post {
  subject_id: Uuid;
  file: string;
}

/**
 * The class's Branch nav order, as one list.
 *
 * Whole-list rather than a move-to-index, because the order is a property of
 * the class and a partial update from one co-teacher would silently renumber
 * another's branches.
 */
export interface BranchOrder {
  subject_ids?: Uuid[];
}

/**
 * A new Theme.
 *
 * Lived in `api/v1/curriculum.py` until now, which put it outside the file
 * the client's types are generated from — so `POST /chapters` was the one
 * write in the API whose request shape the contract gate could not see
 * (audit 02, M11).
 */
export interface ChapterCreate {
  subject_id: Uuid;
  key: string;
  labels: Record<string, string>;
  position?: number;
  competency_ids?: Uuid[];
}

export interface ChapterOut {
  id: Uuid;
  key: string;
  labels: Record<string, string>;
  position: number;
  competency_ids: Uuid[];
  primary_competency_id: Uuid | null;
}

export interface ChapterUpdate {
  labels?: Record<string, string> | null;
  position?: number | null;
  competency_ids?: Uuid[] | null;
}

export interface ClassCreate {
  code: string;
  label?: string | null;
  school_year_id?: Uuid | null;
}

export interface ClassOut {
  id: Uuid;
  code: string;
  label: string | null;
  school_year_id: Uuid | null;
  student_count: number;
  subject_ids: Uuid[];
  declared_subject_ids: Uuid[];
  head_teacher_id: Uuid | null;
  is_head: boolean;
  teachers: ClassTeacherOut[];
}

export interface ClassPointsOut {
  class_id: Uuid;
  students: StudentPointsOut[];
  sheets: ClassSheetPointsOut[];
}

export interface ClassSheetPointsOut {
  sheet_id: Uuid;
  sheet_title: string;
  average_ratio: number | null;
  students: StudentPointsOut[];
}

export interface ClassSummary {
  class_id: Uuid;
  code: string;
  label: string | null;
  student_count: number;
  last_sheet_title: string | null;
  last_sheet_at: IsoDateTime | null;
  pending_scans: number;
  students_needing_attention: number;
  band_counts: Record<string, number>;
}

/** One teacher's footing in one class. */
export interface ClassTeacherOut {
  teacher_id: Uuid;
  first_name: string;
  last_name: string;
  subject_ids: Uuid[];
  is_head: boolean;
}

export interface ClassTreeOut {
  class_id: Uuid;
  branches: TreeBranchOut[];
  computed_at: IsoDateTime;
}

export interface ClassUpdate {
  label?: string | null;
  code?: string | null;
}

/**
 * A teacher in the same school, for the branch picker.
 *
 * Deliberately no ``email``: a picker has no reason to know colleagues'
 * addresses, and ``TeacherOut`` already exists for the signed-in user.
 */
export interface ColleagueOut {
  id: Uuid;
  first_name: string;
  last_name: string;
}

/** The drill-down payload for one (student, competency) cell. */
export interface CompetencyAttemptsOut {
  student: StudentOut;
  competency: CompetencyOut;
  score: number;
  band: MasteryBand;
  provisional: boolean;
  days_until_review: number | null;
  attempts: AttemptOut[];
}

/**
 * One page of the curriculum.
 *
 * Small today because the seeded PER tree is two levels deep and invented;
 * the real one is five levels and a few thousand nodes, and this route is
 * what a picker calls (database audit H1).
 */
export interface CompetencyListOut {
  items: CompetencyOut[];
  total: number;
  offset: number;
  limit: number;
}

export interface CompetencyMastery {
  competency: CompetencyOut;
  score: number;
  band: MasteryBand;
  attempts_count: number;
  provisional: boolean;
  days_until_review: number | null;
  history: MasteryPoint[];
}

export interface CompetencyOut {
  id: Uuid;
  curriculum: CurriculumKind;
  code: string;
  parent_id: Uuid | null;
  subject_key: string;
  cycle: number;
  labels: Record<string, string>;
  description: Record<string, string>;
}

/** Both Swiss curricula are first-class; neither is the default. */
export type CurriculumKind = 'LP21' | 'PER';

/**
 * A teacher overriding the machine. Always allowed, always recorded.
 *
 * ``le=3`` is the layout's hard ceiling (``MAX_OPTIONS``); the item's own
 * option count is checked in the service, which is the only place that knows
 * it — a two-bubble true/false item must not accept option 3.
 *
 * For a written answer the correction is a verdict and/or a transcription.
 * Sending ``verdict_correct: null`` explicitly means "I cannot tell either";
 * leaving it out keeps the verdict as it was.
 */
export interface DetectionCorrection {
  detected_index?: number | null;
  verdict_correct?: boolean | null;
  transcription?: string | null;
}

/**
 * One page of readings from a scanned pile.
 *
 * A pile is one page per pupil per sheet page, and each page carries one
 * detection per item — twenty-eight copies of a twelve-item sheet is 336
 * rows, each with its fill ratios, its bubble boxes and a presigned crop
 * URL. The review screen reads them all at once and re-reads them on every
 * correction (audit 02, M4).
 */
export interface DetectionListOut {
  items: DetectionOut[];
  total: number;
  offset: number;
  limit: number;
}

export interface DetectionOut {
  id: Uuid;
  item_index: number;
  sheet_item_id: Uuid | null;
  exercise_id: Uuid | null;
  detected_index: number | null;
  detected_bool: boolean | null;
  confidence: number;
  outcome: DetectionOutcome;
  fill_ratios: number[] | null;
  bubble_boxes: Record<string, number>[] | null;
  corrected_at: IsoDateTime | null;
  machine_index: number | null;
  machine_outcome: DetectionOutcome | null;
  machine_confidence: number | null;
  number: number | null;
  statement: string | null;
  options: string[] | null;
  option_letters: string | null;
  exercise_type: ExerciseType | null;
  ai_generated: boolean;
  answer_index: number | null;
  crop_url: string | null;
  transcription: string | null;
  verdict_correct: boolean | null;
  machine_transcription: string | null;
  machine_verdict_correct: boolean | null;
  vision_model: string | null;
  answer_text: string | null;
  reference_answer: string | null;
}

/** How a single item's answer was arrived at — the audit trail matters. */
export type DetectionOutcome = 'detected' | 'low_confidence' | 'blank' | 'multiple' | 'corrected' | 'not_gradeable' | 'pending';

/**
 * What happened, in the teacher's vocabulary rather than the schema's.
 *
 * An append-only log rather than a column per lifecycle moment. `updated_at`
 * cannot answer "when was this confirmed" — it is overwritten by the next
 * edit to the row, whatever that edit was — and two of the moments a teacher
 * most wants back (a sheet printed, a pile confirmed) had no timestamp at all.
 *
 * The names are what a teacher would say happened, because they are read back
 * as a sentence in the agenda, not as a status field.
 */
export type EventKind = 'source_imported' | 'chapter_read' | 'sheet_created' | 'sheet_rendered' | 'sheet_printed' | 'scan_uploaded' | 'scan_confirmed' | 'scan_reopened' | 'adaptive_proposed' | 'adaptive_exported' | 'feedback_written' | 'feedback_approved' | 'teacher_joined' | 'teacher_left' | 'exercise_approved' | 'exercise_edited';

/** Which row the event is about, so the agenda can link back to it. */
export type EventSubject = 'source' | 'sheet' | 'scan' | 'class' | 'teacher' | 'exercise';

/**
 * An exercise the teacher wrote in the sheet builder.
 *
 * Lands as `ExerciseOrigin.TEACHER`: not a transcription, so it carries no
 * source or page, and not a model's proposal, so it wears no accent and needs
 * no approval. The teacher approved it by writing it.
 */
export interface ExerciseCreate {
  subject_id: Uuid;
  type: ExerciseType;
  language: 'fr' | 'de' | 'en';
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

/**
 * Counts for the filter chips, computed over the *unfiltered-by-type* set.
 *
 * The chips have to show what selecting them would give, so these are counted
 * with every filter applied except the one each chip controls. A chip reading
 * "QCM · 0" is useful; a chip that silently yields nothing is not.
 */
export interface ExerciseFacets {
  total: number;
  mcq: number;
  true_false: number;
  open: number;
}

/**
 * One page of exercises.
 *
 * `GET /sources/{id}/exercises` used to return every row of a document in a
 * single unpaginated array — fine for a 40-exercise worksheet, roughly two
 * megabytes of JSON for a textbook, through a Worker proxy, into a list of a
 * thousand React rows. Filtering and paging both happen in Postgres now.
 */
export interface ExerciseListOut {
  items: ExerciseOut[];
  total: number;
  offset: number;
  limit: number;
  facets: ExerciseFacets;
}

export type ExerciseOrigin = 'textbook' | 'ai_generated' | 'teacher';

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
  label: string | null;
  title: string | null;
  figure_url: string | null;
  figure_width_mm: number | null;
  figure_height_mm: number | null;
  approved_at: IsoDateTime | null;
}

export interface ExerciseProposal {
  exercise: ExerciseOut;
  score: number;
  provenance: Provenance;
}

export type ExerciseType = 'mcq' | 'true_false' | 'open';

/**
 * A correction to an extracted or generated exercise.
 *
 * Every field a teacher may rewrite carries the same bound its `ExerciseCreate`
 * counterpart carries. An edit is not a lesser write than a creation: the row it
 * lands in is the row the sheet renderer paginates and the printed grid draws its
 * bubbles from, so a statement PATCH may not smuggle in what POST would refuse.
 */
export interface ExerciseUpdate {
  statement?: string | null;
  options?: string[] | null;
  answer_index?: number | null;
  answer_bool?: boolean | null;
  answer_text?: string | null;
  explanation?: string | null;
  difficulty?: number | null;
  approved?: boolean | null;
}

/** One answer, as it was recorded. The evidence, not the band over it. */
export interface ExportAttempt {
  answered_at: IsoDateTime;
  exercise_id: Uuid;
  competency_codes: string[];
  correct: boolean;
  score: number;
  difficulty: number;
  sheet_id: Uuid | null;
  sheet_title: string | null;
}

/** One year's enrolment record. A pupil has one per year they were here. */
export interface ExportEnrolment {
  student_id: Uuid;
  uid: string;
  number: number | null;
  class_id: Uuid | null;
  class_code: string | null;
  school_year: string | null;
  is_home_class: boolean;
  valid_from: string | null;
  valid_to: string | null;
}

/**
 * A misconception note. Free text a teacher or a model wrote ABOUT the
 * child, which is the most sensitive thing in the record and the reason the
 * export exists as more than a list of marks.
 */
export interface ExportNote {
  created_at: IsoDateTime;
  subject_id: Uuid;
  language: string;
  notes: string[];
  based_on_sheet_id: Uuid | null;
  approved_at: IsoDateTime | null;
}

/** The only way a generated note becomes printable. */
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

/** Start the per-student feedback job for one corrected common sheet. */
export interface FeedbackGenerateRequest {
  class_id: Uuid;
  subject_id: Uuid;
  source_sheet_id: Uuid;
  language?: 'fr' | 'de' | 'en' | null;
}

export interface HTTPValidationError {
  detail: ValidationError[];
}

/**
 * READINESS: should this instance be sent traffic?
 *
 * Three connections, and a `degraded` answer when any of them is down. See
 * `LivenessOut` for why the two are different questions.
 */
export interface HealthOut {
  status: 'ok' | 'degraded';
  version: string;
  database: boolean;
  redis: boolean;
  storage: boolean;
}

export interface HomeOut {
  teacher: TeacherOut;
  subjects: SubjectOut[];
  classes: ClassSummary[];
}

/** How one printed item was read across the class's copies. */
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

export type JobKind = 'ingest_source' | 'extract_section' | 'render_sheet' | 'process_scan' | 'propose_adaptive' | 'generate_adaptive' | 'generate_feedback' | 'grade_open_answers';

export interface JobOut {
  id: Uuid;
  kind: JobKind;
  status: JobStatus;
  progress: number;
  message: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: IsoDateTime;
  finished_at: IsoDateTime | null;
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed';

/**
 * LIVENESS: is this process running?
 *
 * Deliberately smaller than `HealthOut`, because it must not be able to grow
 * a dependency check. A liveness probe that touches Redis turns a Redis
 * outage into a restart loop across every API pod (audit 03, B29).
 */
export interface LivenessOut {
  status: string;
  version: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

/** The ordered domain scale. Order is meaningful: BAND_ORDER below. */
export type MasteryBand = 'solid' | 'ok' | 'weak' | 'fading' | 'none';

export interface MasteryCell {
  student_id: Uuid;
  competency_id: Uuid;
  score: number;
  band: MasteryBand;
  attempts_count: number;
  provisional: boolean;
  days_until_review: number | null;
  last_attempt_at: IsoDateTime | null;
}

export interface MasteryMatrixOut {
  class_id: Uuid;
  students: StudentOut[];
  competencies: CompetencyOut[];
  cells: MasteryCell[];
  computed_at: IsoDateTime;
}

export interface MasteryPoint {
  at: IsoDateTime;
  score: number;
  band: MasteryBand;
}

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

/**
 * Where a proposal came from. The teacher audits this, so it must be
 * specific enough to check against the book on the desk.
 */
export interface Provenance {
  source_id: Uuid | null;
  source_filename: string | null;
  page: number | null;
  excerpt: string | null;
  similarity: number | null;
  reason: string;
}

/** Paste a roster, one student per line. The teacher's real workflow. */
export interface RosterCreate {
  students: StudentCreate[];
}

export interface ScanConfirmResponse {
  attempts_created: number;
  students_affected: number;
  competencies_updated: number;
  attempts_superseded: number;
  items_skipped: number;
}

export interface ScanOut {
  id: Uuid;
  sheet_id: Uuid | null;
  original_filename: string;
  status: ScanStatus;
  error: string | null;
  job_id: Uuid | null;
  pages: ScanPageOut[];
  revised: boolean;
  reopened_at: IsoDateTime | null;
  confirmed_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

/** Manual fallback when the printed UID could not be read. */
export interface ScanPageAssign {
  student_id: Uuid;
}

/** Take a page out of the pile, or put it back. */
export interface ScanPageDiscard {
  discarded?: boolean;
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
  wrong_class: boolean;
  discarded: boolean;
  page_in_copy: number | null;
  registration_error: string | null;
  flags: string[];
  detections: DetectionOut[];
  corrections_dropped: number[];
}

export type ScanStatus = 'uploaded' | 'processing' | 'needs_review' | 'confirmed' | 'failed';

/** What reopening a pile withdrew, and what it put back. */
export interface ScanUnvalidateResponse {
  attempts_removed: number;
  attempts_rederived: number;
  students_affected: number;
  competencies_updated: number;
}

/**
 * A second establishment, created from the product rather than the seed.
 *
 * `default_curriculum` IS settable here and nowhere else: it is resolved into
 * every `Chapter.primary_competency_id` the moment the school gets chapters
 * (D56), so the one safe time to choose it is before any exist.
 */
export interface SchoolCreate {
  name: string;
  canton?: string | null;
  default_curriculum?: CurriculumKind;
}

export interface SchoolOut {
  id: Uuid;
  name: string;
  canton: string | null;
  default_curriculum: CurriculumKind | null;
}

export interface SchoolUpdate {
  name?: string | null;
  canton?: string | null;
}

/**
 * One school year of this establishment.
 *
 * Every read in this API answers "now" unless told otherwise, which is fine
 * until August. `label` is what a teacher recognises ("2026/27"); the two
 * dates are what a query needs, and `is_current` is the one the screens
 * default to. Without a route to list these there was no way to DISCOVER a
 * year id, so `school_year_id` as a filter would have been unaskable
 * (audit 02, C3).
 */
export interface SchoolYearOut {
  id: Uuid;
  label: string;
  starts_on: string;
  ends_on: string;
  is_current: boolean;
}

export interface SheetConfidenceOut {
  sheet_id: Uuid;
  items: ItemConfidenceOut[];
}

export interface SheetCreate {
  class_id: Uuid;
  subject_id: Uuid;
  chapter_id?: Uuid | null;
  title: string;
  language: 'fr' | 'de' | 'en';
  target?: SheetTarget;
  intent?: string | null;
  items: SheetItemIn[];
  default_points_correct?: number;
  default_points_penalty?: number;
}

/**
 * A sheet that does not exist yet, rendered so the teacher can see it.
 *
 * The builder needs a preview while the teacher is still reordering, and the
 * two obvious ways to get one are both wrong. Redrawing the page in React
 * duplicates the millimetre geometry that `sheets.layout` owns and that the
 * scan detector reads — the previous hand-rolled attempt put the bubbles
 * inline instead of on the fixed grid and printed A/B/C/D where the sheet
 * prints V/F. Creating a real draft `Sheet` and PATCHing it writes a row plus
 * one `SheetInstance` per student on every keystroke, and leaves a junk sheet
 * behind whenever the teacher walks away.
 *
 * So the draft is posted and rendered, never stored. The response is the same
 * markup `GET /sheets/{id}/preview` returns, from the same `SheetData`.
 */
export interface SheetDraftPreview {
  class_id: Uuid;
  subject_id: Uuid;
  title?: string;
  language: 'fr' | 'de' | 'en';
  items: SheetItemIn[];
  default_points_correct?: number;
  default_points_penalty?: number;
}

export interface SheetInstanceOut {
  id: Uuid;
  student_id: Uuid;
  student_uid: string;
  page_count: number | null;
  group_label: string | null;
  has_feedback: boolean;
  points_earned: number | null;
  points_possible: number;
}

export interface SheetItemIn {
  exercise_id: Uuid;
  position: number;
  statement_override?: string | null;
  answer_box_lines?: number | null;
  answer_box_fill?: AnswerBoxFill | null;
  expected_answer?: string | null;
  points_correct?: number | null;
  points_penalty?: number | null;
}

export interface SheetItemOut {
  id: Uuid;
  position: number;
  statement_override: string | null;
  answer_box_lines: number | null;
  answer_box_fill: AnswerBoxFill | null;
  expected_answer: string | null;
  points_correct: number | null;
  points_penalty: number | null;
  exercise: ExerciseOut;
}

export type SheetKind = 'blank' | 'answer_key' | 'feedback';

/**
 * How a class did on one sheet, in the product's own five bands.
 *
 * `TreeMasteryOut`, not a new shape: a sheet band is the same kind of
 * aggregate as a Theme band and carries the same coverage, so it reads and
 * prints through the components that already exist (DC-content-07).
 *
 * `overall` pools the students the way `pool_by_competency` does — across
 * pupils, which is sound — and never across competencies, which is not
 * (I-mastery-10).
 */
export interface SheetMasteryOut {
  sheet_id: Uuid;
  competency_ids: Uuid[];
  students: SheetStudentMastery[];
  overall: TreeMasteryOut;
  computed_at: IsoDateTime;
}

export interface SheetOut {
  id: Uuid;
  class_id: Uuid;
  subject_id: Uuid;
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
  feedback_pdf_url: string | null;
  derived_from_id: Uuid | null;
  source_sheet_ids: Uuid[];
  scans: SheetScanOut[];
  competency_ids: Uuid[];
  chapter_ids: Uuid[];
  rendered_at: IsoDateTime | null;
  printed_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

export interface SheetProposeRequest {
  class_id: Uuid;
  subject_id: Uuid;
  chapter_ids?: Uuid[];
  intent?: string | null;
  count?: number;
  language?: 'fr' | 'de' | 'en' | null;
  difficulty?: number | null;
}

export interface SheetProposeResponse {
  proposals: ExerciseProposal[];
  language: string;
}

/**
 * One pile photographed against a sheet, as the sheet lists it.
 *
 * Deliberately not `ScanOut`: that carries every page and every detection,
 * and a sheet showing four scans would ship four page lists nobody asked for.
 * What a sheet needs is a route back to its corrections and the one word that
 * says where each pile got to.
 */
export interface SheetScanOut {
  id: Uuid;
  status: ScanStatus;
  revised: boolean;
  confirmed_at: IsoDateTime | null;
  reopened_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

/** One student's band on one sheet. */
export interface SheetStudentMastery {
  student_id: Uuid;
  mastery: TreeMasteryOut;
}

/**
 * One sheet a student actually sat, newest first on the profile.
 *
 * ``scan_id`` is the pile the marks were read from, so the teacher can get
 * from "she did badly here" back to the photograph of her copy in one click.
 */
export interface SheetTaken {
  sheet_id: Uuid;
  title: string;
  answered_at: IsoDateTime;
  attempts_count: number;
  correct_count: number;
  scan_id: Uuid | null;
  chapter_id: Uuid | null;
  mastery: TreeMasteryOut | null;
}

export type SheetTarget = 'class' | 'student' | 'group';

export interface SheetUpdate {
  title?: string | null;
  chapter_id?: Uuid | null;
  items?: SheetItemIn[] | null;
  default_points_correct?: number | null;
  default_points_penalty?: number | null;
}

export interface SourceOut {
  id: Uuid;
  subject_id: Uuid;
  filename: string;
  title: string | null;
  publisher: string | null;
  isbn: string | null;
  url: string | null;
  content_type: string;
  size_bytes: number;
  language: string | null;
  page_count: number | null;
  status: JobStatus;
  error: string | null;
  notice: string | null;
  exercise_count: number;
  section_count: number;
  created_at: IsoDateTime;
}

/**
 * One chapter of the document, as the document declares it.
 *
 * Distinct from `ChapterOut`: that is the teacher's curriculum grouping and an
 * exercise reaches one only by competency inference, so it is allowed to be
 * null. This one is a fact about the file and is always set, which is why the
 * builder filters on it first.
 */
export interface SourceSectionOut {
  id: Uuid;
  title: string;
  label: string | null;
  page_from: number;
  page_to: number;
  position: number;
  exercise_count: number;
  extracted_at: IsoDateTime | null;
  extraction_notice: string | null;
}

export interface SourceUpdate {
  title?: string | null;
  language?: string | null;
  publisher?: string | null;
  isbn?: string | null;
  url?: string | null;
}

/**
 * The pupil's own identifier, typed back, for an irreversible act.
 *
 * A BODY, not a query string. `DELETE /students/{id}?confirm=7B_15` put a
 * pupil's identifier in the URL — the one place it is certain to be written
 * down: access logs, proxy logs, browser history, and an address bar on a
 * screen that is regularly projected onto a classroom wall. It was the only
 * student identifier anywhere in this API's URLs (audit 02, M9).
 *
 * Not a boolean: a caller firing at the wrong row must fail rather than
 * destroy or anonymise the wrong child, and the uid is the one string that
 * is unambiguous and in front of the teacher on the paper.
 *
 * `validate_uid` is what checks it, and had been defined and wired into
 * nothing since it was written (M8).
 */
export interface StudentConfirmation {
  confirm: string;
}

export interface StudentCreate {
  first_name: string;
  last_name: string;
  number?: number | null;
}

/**
 * Everything this establishment holds about one pupil, in one document.
 *
 * A parent may ask what is held; a school leaving Alppy has to be able to
 * take it. Before this the only way out of the product was the destructive
 * one, which is a poor answer to "what do you have on my child".
 *
 * Spans every year: the durable identity is `Person`, and `Student` is one
 * year's enrolment record (0028). A pupil who repeats a year has two
 * enrolments and one continuous record of evidence.
 *
 * Mastery snapshots are deliberately NOT here. They are recomputed from the
 * attempts below — the score decays, so a snapshot is a photograph of a
 * calculation and not an independent fact about the child. Exporting them
 * would imply the school holds two things where it holds one.
 */
export interface StudentExportOut {
  generated_at: IsoDateTime;
  person_id: Uuid;
  first_name: string | null;
  last_name: string | null;
  anonymised_at: IsoDateTime | null;
  enrolments: ExportEnrolment[];
  attempts: ExportAttempt[];
  notes: ExportNote[];
}

export interface StudentOut {
  id: Uuid;
  uid: string;
  number: number;
  first_name: string | null;
  last_name: string | null;
  anonymised_at: IsoDateTime | null;
  home_class_code: string;
  class_codes: string[];
}

/**
 * One student's marks. Field names match ``SheetInstanceOut`` on purpose:
 * the same two numbers, aggregated one level up.
 */
export interface StudentPointsOut {
  student_id: Uuid;
  points_earned: number | null;
  points_possible: number;
}

export interface StudentProfileOut {
  student: StudentOut;
  overall_score: number;
  strengths: CompetencyMastery[];
  gaps: CompetencyMastery[];
  all_competencies: CompetencyMastery[];
  sheets_taken: number;
  sheets: SheetTaken[];
}

/** One question, as one student answered it. */
export interface StudentSheetItemOut {
  position: number;
  number: number | null;
  exercise_id: Uuid;
  statement: string;
  exercise_type: ExerciseType;
  ai_generated: boolean;
  options: string[];
  given: string | null;
  given_index: number | null;
  expected: string | null;
  expected_index: number | null;
  outcome: DetectionOutcome | null;
  confidence: number | null;
  correct: boolean | null;
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

/** Names only. `uid` and `number` are on paper. */
export interface StudentUpdate {
  first_name?: string | null;
  last_name?: string | null;
}

/** A new Branch. `key` is the join key, `labels` is what a teacher reads. */
export interface SubjectCreate {
  key: string;
  labels?: Record<string, string>;
}

export interface SubjectOut {
  id: Uuid;
  key: string;
  labels: Record<string, string>;
}

/** Only the labels. `key` is what `Competency.subject_key` matches on. */
export interface SubjectUpdate {
  labels: Record<string, string>;
}

export interface TeacherOut {
  id: Uuid;
  email: string;
  first_name: string;
  last_name: string;
  school_id: Uuid;
  schools: SchoolOut[];
  preferences: TeacherPreferences;
}

/**
 * The display switches. None is a real value: "not chosen" differs from
 * "light", because not chosen means follow the system.
 */
export interface TeacherPreferences {
  locale: 'fr' | 'de' | 'en';
  theme: 'light' | 'dark' | null;
  contrast: string | null;
  motion: string | null;
  calm: string | null;
  discreet: string | null;
}

/**
 * One line of the agenda.
 *
 * ``title`` is resolved from the row the event points at when it still
 * exists, and falls back to the stored ``summary`` when it does not — an
 * event outlives its subject, because deleting a sheet does not un-print it.
 */
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
  detail: Record<string, unknown>;
  resolved: boolean;
}

/**
 * How many events each kind would give under the CURRENT filters.
 *
 * Computed with every filter except the kind filter itself: a chip has to
 * report what selecting it would give, not what is already selected.
 */
export interface TimelineFacets {
  by_kind: Record<string, number>;
}

export interface TimelineOut {
  items: TimelineEventOut[];
  total: number;
  offset: number;
  limit: number;
  facets: TimelineFacets;
}

export interface TreeBranchOut {
  subject_id: Uuid;
  subject_key: string;
  labels: Record<string, string>;
  mastery: TreeMasteryOut;
  competences: TreeCompetenceOut[];
  unfiled_sheet_count: number;
  unfiled_exercise_count: number;
}

export interface TreeCompetenceOut {
  competency_id: Uuid;
  code: string;
  labels: Record<string, string>;
  mastery: TreeMasteryOut;
  themes: TreeThemeOut[];
}

/**
 * A rolled-up band. The SAME five bands as a matrix cell, deliberately.
 *
 * ``roll_up_mastery`` returns a ``MasteryResult`` through the same
 * ``band_for`` thresholds, so a Theme or a Branch needs no new colour, no new
 * label set and no second reading of DC-colour-08 — the shipped band tokens,
 * glyphs and written labels already cover it.
 *
 * Two fields do NOT mean at this level what they mean on a cell, and the
 * difference is documented in docs/mastery-model.md §6 rather than papered
 * over: ``score`` is a weighted mean of the children's already-decayed
 * scores, so it is NOT ``accuracy * recency`` here; ``days_until_review`` is
 * the earliest of the children's, not a re-derivation.
 */
export interface TreeMasteryOut {
  score: number;
  band: MasteryBand;
  attempts_count: number;
  provisional: boolean;
  assessed_count: number;
  child_count: number;
  weakest_band: MasteryBand | null;
  days_until_review: number | null;
  last_attempt_at: IsoDateTime | null;
}

export interface TreeThemeOut {
  chapter_id: Uuid;
  key: string;
  labels: Record<string, string>;
  position: number;
  sheet_count: number;
  competency_ids: Uuid[];
  mastery: TreeMasteryOut;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input: unknown;
  ctx: Record<string, unknown>;
}
