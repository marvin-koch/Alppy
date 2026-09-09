import { apiRequest, apiRequestText } from './client';
import type {
  ClassTreeOut,
  AdaptiveApproveRequest,
  AdaptiveApproveResponse,
  AdaptiveBatchRequest,
  AdaptiveDiscardRequest,
  AdaptiveDiscardResponse,
  AdaptiveProposeRequest,
  AdaptiveProposeResponse,
  AdaptiveRegenerateRequest,
  AdaptiveRegenerateResponse,
  ChapterOut,
  ClassCreate,
  ClassOut,
  ClassPointsOut,
  CompetencyAttemptsOut,
  CompetencyOut,
  CurriculumKind,
  DetectionCorrection,
  DetectionOut,
  ExerciseCreate,
  ExerciseListOut,
  ExerciseOut,
  ExerciseQuery,
  ExerciseUpdate,
  FeedbackApproveRequest,
  FeedbackApproveResponse,
  FeedbackDiscardRequest,
  FeedbackDiscardResponse,
  FeedbackGenerateRequest,
  HomeOut,
  JobOut,
  LoginRequest,
  MasteryMatrixOut,
  MatrixSort,
  MisconceptionNoteOut,
  RosterCreate,
  ScanConfirmResponse,
  ScanOut,
  ScanPageAssign,
  ScanPageDiscard,
  ScanPageOut,
  ScanUnvalidateResponse,
  SheetConfidenceOut,
  SheetCreate,
  SheetDraftPreview,
  SheetOut,
  SheetProposeRequest,
  SheetProposeResponse,
  SheetUpdate,
  SourceOut,
  SourceSectionOut,
  StudentOut,
  StudentProfileOut,
  StudentSheetOut,
  SubjectOut,
  TeacherOut,
  TeacherPreferences,
  TimelineOut,
  TimelineQuery,
  Uuid,
} from './types';

/**
 * The API surface of `docs/plan.md` §4, typed against `alppy/schemas`.
 *
 * Three routes are not spelled out in §4 but are required by the screens in §5
 * and have a schema waiting for them, so they are called at the obvious path
 * and flagged in the handover rather than invented into the schema:
 *   · `GET /home`            -> HomeOut        (screen 2 needs the summary)
 *   · `GET /sources`         -> SourceOut[]    (screen 5 lists them)
 *   · `PATCH /exercises/{id}`-> ExerciseOut    (ExerciseUpdate has no route)
 *
 * Every path below is checked against the served OpenAPI document by
 * `apps/web/src/lib/api/__tests__/contract.test.ts`. Guessing at "the obvious
 * path" is how `POST /scans/{id}/pages/{id}/assign` came to be called for two
 * milestones against an API that only ever exposed `PATCH …/pages/{id}`.
 */

/* --------------------------------------------------------------- auth --- */
export const login = (body: LoginRequest) =>
  apiRequest<TeacherOut>('/auth/login', { method: 'POST', body });

export const logout = () => apiRequest<void>('/auth/logout', { method: 'POST' });

export const getMe = () => apiRequest<TeacherOut>('/auth/me');

export const updatePreferences = (body: Partial<TeacherPreferences>) =>
  apiRequest<TeacherOut>('/teachers/me/preferences', { method: 'PATCH', body });

/* --------------------------------------------------------------- home --- */
export const getHome = () => apiRequest<HomeOut>('/home');

/* ------------------------------------------------------------ classes --- */
export const listClasses = () => apiRequest<ClassOut[]>('/classes');

export const createClass = (body: ClassCreate) =>
  apiRequest<ClassOut>('/classes', { method: 'POST', body });

export const getClass = (classId: Uuid) => apiRequest<ClassOut>(`/classes/${classId}`);

export const addStudents = (classId: Uuid, body: RosterCreate) =>
  apiRequest<StudentOut[]>(`/classes/${classId}/students`, { method: 'POST', body });

export const listStudents = (classId: Uuid) =>
  apiRequest<StudentOut[]>(`/classes/${classId}/students`);

export const createRoster = (classId: Uuid, body: RosterCreate) =>
  apiRequest<StudentOut[]>(`/classes/${classId}/students`, { method: 'POST', body });

export const listSubjects = () => apiRequest<SubjectOut[]>('/subjects');

export const listCompetencies = (kind: CurriculumKind, subjectKey?: string) =>
  apiRequest<CompetencyOut[]>(`/curricula/${kind}/competencies`, {
    query: { subject_key: subjectKey },
  });

export const listChapters = (subjectId?: Uuid) =>
  apiRequest<ChapterOut[]>('/chapters', { query: { subject_id: subjectId } });

/* ------------------------------------------------------------ sources --- */
export const listSources = () => apiRequest<SourceOut[]>('/sources');

export const getSource = (sourceId: Uuid) => apiRequest<SourceOut>(`/sources/${sourceId}`);

export const getSourceStatus = (sourceId: Uuid) =>
  apiRequest<SourceOut>(`/sources/${sourceId}/status`);

export const listSourceSections = (sourceId: Uuid) =>
  apiRequest<SourceSectionOut[]>(`/sources/${sourceId}/sections`);

/** Read one chapter for exercises. Returns the job to poll — a chapter is
 *  dozens of model calls, which is not something a request holds open. */
export const extractSourceSection = ({
  sourceId,
  sectionId,
}: {
  sourceId: Uuid;
  sectionId: Uuid;
}) =>
  apiRequest<JobOut>(`/sources/${sourceId}/sections/${sectionId}/extract`, { method: 'POST' });

/** Filtered and paginated in Postgres. A textbook is a thousand exercises and
 *  the client is behind a Worker proxy, so the whole document never travels. */
export const listSourceExercises = (sourceId: Uuid, query: ExerciseQuery = {}) =>
  apiRequest<ExerciseListOut>(`/sources/${sourceId}/exercises`, {
    query: { ...query },
  });

/** `POST /sources` starts an ingestion job; the API may answer with either shape.
 *
 * `subject_id` is required by the API — a source is always filed under a
 * subject, because that is what scopes retrieval later. Omitting it made every
 * upload a silent 422. */
export const uploadSource = ({ file, subjectId }: { file: File; subjectId: Uuid }) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('subject_id', subjectId);
  return apiRequest<SourceOut | JobOut>('/sources', { method: 'POST', formData });
};

/* ---------------------------------------------------------- exercises --- */
export const updateExercise = (exerciseId: Uuid, body: ExerciseUpdate) =>
  apiRequest<ExerciseOut>(`/exercises/${exerciseId}`, { method: 'PATCH', body });

/** An exercise the teacher wrote. Lands in the corpus as `origin: 'teacher'`,
 *  so it is reusable next term and wears no accent. */
export const createExercise = (body: ExerciseCreate) =>
  apiRequest<ExerciseOut>('/exercises', { method: 'POST', body });

/* ------------------------------------------------------------- sheets --- */
export const proposeSheet = (body: SheetProposeRequest) =>
  apiRequest<SheetProposeResponse>('/sheets/propose', { method: 'POST', body });

/** The print document for an unsaved sheet, as HTML. Nothing is persisted. */
export const previewSheetDraft = (body: SheetDraftPreview) =>
  apiRequestText('/sheets/preview', { method: 'POST', body });

export const createSheet = (body: SheetCreate) =>
  apiRequest<SheetOut>('/sheets', { method: 'POST', body });

export const updateSheet = (sheetId: Uuid, body: SheetUpdate) =>
  apiRequest<SheetOut>(`/sheets/${sheetId}`, { method: 'PATCH', body });

export const getSheet = (sheetId: Uuid) => apiRequest<SheetOut>(`/sheets/${sheetId}`);

/** Every sheet the teacher has built. Without this a sheet was reachable only
 *  by the redirect that follows creating it. */
export const listSheets = (classId?: Uuid, subjectId?: Uuid) =>
  apiRequest<SheetOut[]>('/sheets', { query: { class_id: classId, subject_id: subjectId } });

export const listScans = (sheetId?: Uuid) =>
  apiRequest<ScanOut[]>('/scans', { query: { sheet_id: sheetId } });

export const renderSheet = (sheetId: Uuid) =>
  apiRequest<JobOut>(`/sheets/${sheetId}/render`, { method: 'POST' });

/* -------------------------------------------------------------- scans --- */
/**
 * One pile, however many files the teacher selected.
 *
 * `sheetId` is required, not optional: without it the pipeline has no answer
 * key and no per-copy pagination, so it reads every mark and grades nothing.
 */
export const uploadScan = (files: File[], sheetId: Uuid) => {
  const formData = new FormData();
  for (const file of files) formData.append('files', file);
  formData.append('sheet_id', sheetId);
  return apiRequest<ScanOut>('/scans', { method: 'POST', formData });
};

export const getScan = (scanId: Uuid) => apiRequest<ScanOut>(`/scans/${scanId}`);

export const listDetections = (scanId: Uuid) =>
  apiRequest<DetectionOut[]>(`/scans/${scanId}/detections`);

export const correctDetection = (scanId: Uuid, detectionId: Uuid, body: DetectionCorrection) =>
  apiRequest<DetectionOut>(`/scans/${scanId}/detections/${detectionId}`, {
    method: 'PATCH',
    body,
  });

export const assignScanPage = (scanId: Uuid, pageId: Uuid, body: ScanPageAssign) =>
  apiRequest<ScanPageOut>(`/scans/${scanId}/pages/${pageId}`, { method: 'PATCH', body });

/** Who this scan's pages may be assigned to: the sheet's own class, nobody else. */
export const listScanStudents = (scanId: Uuid) =>
  apiRequest<StudentOut[]>(`/scans/${scanId}/students`);

/** Take a page out of the pile, or put it back. */
export const discardScanPage = (scanId: Uuid, pageId: Uuid, body: ScanPageDiscard) =>
  apiRequest<ScanPageOut>(`/scans/${scanId}/pages/${pageId}/discard`, {
    method: 'POST',
    body,
  });

export const confirmScan = (scanId: Uuid) =>
  apiRequest<ScanConfirmResponse>(`/scans/${scanId}/confirm`, { method: 'POST' });

/** Take a confirmed pile back into review, withdrawing the grades it wrote. */
export const reopenScan = (scanId: Uuid) =>
  apiRequest<ScanUnvalidateResponse>(`/scans/${scanId}/reopen`, { method: 'POST' });

/** Undo one correction, restoring exactly what the machine read. */
export const revertDetection = (scanId: Uuid, detectionId: Uuid) =>
  apiRequest<DetectionOut>(`/scans/${scanId}/detections/${detectionId}/revert`, {
    method: 'POST',
  });

/* ------------------------------------------------------------ reports --- */
export const getClassPoints = (
  classId: Uuid,
  options: { subjectId?: Uuid; chapterId?: Uuid } = {},
) =>
  apiRequest<ClassPointsOut>(`/classes/${classId}/points`, {
    query: { subject_id: options.subjectId, chapter_id: options.chapterId },
  });

export const getStudentSheet = (studentId: Uuid, sheetId: Uuid) =>
  apiRequest<StudentSheetOut>(`/students/${studentId}/sheets/${sheetId}`);

export const getSheetConfidence = (sheetId: Uuid) =>
  apiRequest<SheetConfidenceOut>(`/sheets/${sheetId}/confidence`);

/* ------------------------------------------------------------ mastery --- */
/**
 * Branch -> Competence -> Theme, every node carrying a rolled-up band.
 *
 * Lives under `/classes/{id}/` and not under `/subjects/` because the bands
 * are a fact about THIS class's attempts, not about the curriculum: the same
 * tree read for 7B and for 9A returns different numbers on the same nodes.
 */
export const getClassTree = (
  classId: Uuid,
  options: { subjectId?: Uuid; studentId?: Uuid } = {},
) =>
  apiRequest<ClassTreeOut>(`/classes/${classId}/tree`, {
    query: { subject_id: options.subjectId, student_id: options.studentId },
  });

export const getClassMastery = (
  classId: Uuid,
  options: { subjectId?: Uuid; chapterId?: Uuid; sort?: MatrixSort } = {},
) =>
  apiRequest<MasteryMatrixOut>(`/classes/${classId}/mastery`, {
    query: {
      subject_id: options.subjectId,
      chapter_id: options.chapterId,
      // 'roster' is the server default; omitting it keeps the URL (and the
      // react-query key) stable for the unfiltered case.
      sort: options.sort === 'weakest' ? 'weakest' : undefined,
    },
  });

export const getStudentMastery = (studentId: Uuid) =>
  apiRequest<StudentProfileOut>(`/students/${studentId}/mastery`);

export const getCompetencyAttempts = (studentId: Uuid, competencyId: Uuid) =>
  apiRequest<CompetencyAttemptsOut>(
    `/students/${studentId}/competencies/${competencyId}/attempts`,
  );

/* ----------------------------------------------------------- adaptive --- */
/** Queues the planning. Returns the job to poll, NOT the proposal — the model
 *  calls run in the worker, and a request handler never blocks on one. Read the
 *  result with `readAdaptiveProposal` once the job succeeds. */
export const proposeAdaptive = (body: AdaptiveProposeRequest) =>
  apiRequest<JobOut>('/adaptive/propose', { method: 'POST', body });

/** The built proposal. Its own call rather than a field on the job: the screen
 *  polls the job every 900 ms, and a class of 24 is close to a megabyte. */
export const readAdaptiveProposal = (jobId: Uuid) =>
  apiRequest<AdaptiveProposeResponse>(`/adaptive/proposal/${jobId}`)

/**
 * Creating the batch is NOT rendering it. This returns the `SheetOut` it just
 * built (201); `renderAdaptiveBatch` is what starts the job to poll. Typing
 * this as a `JobOut` is what made the export button poll `/jobs/<sheet-id>`
 * forever — `apiRequest<T>` is an unchecked assertion, so nothing caught it.
 */
export const batchAdaptive = (body: AdaptiveBatchRequest) =>
  apiRequest<SheetOut>('/adaptive/batch', { method: 'POST', body });

export const renderAdaptiveBatch = (sheetId: Uuid) =>
  apiRequest<JobOut>(`/adaptive/batch/${sheetId}/render`, { method: 'POST' });

export const approveAdaptive = (body: AdaptiveApproveRequest) =>
  apiRequest<AdaptiveApproveResponse>('/adaptive/approve', { method: 'POST', body });

export const discardAdaptive = (body: AdaptiveDiscardRequest) =>
  apiRequest<AdaptiveDiscardResponse>('/adaptive/discard', { method: 'POST', body });

export const regenerateAdaptive = (body: AdaptiveRegenerateRequest) =>
  apiRequest<AdaptiveRegenerateResponse>('/adaptive/regenerate', { method: 'POST', body });

/* ------------------------------------------------ misconception notes --- */
/**
 * Queued, not synchronous: one model call per student, which a request handler
 * may not block on. Poll the returned job, then re-read `listFeedback`.
 */
export const generateFeedback = (body: FeedbackGenerateRequest) =>
  apiRequest<JobOut>('/adaptive/feedback/generate', { method: 'POST', body });

export const listFeedback = (sourceSheetId: Uuid) =>
  apiRequest<MisconceptionNoteOut[]>('/adaptive/feedback', {
    query: { source_sheet_id: sourceSheetId },
  });

export const approveFeedback = (body: FeedbackApproveRequest) =>
  apiRequest<FeedbackApproveResponse>('/adaptive/feedback/approve', { method: 'POST', body });

export const discardFeedback = (body: FeedbackDiscardRequest) =>
  apiRequest<FeedbackDiscardResponse>('/adaptive/feedback/discard', { method: 'POST', body });

/** Records that the blank sheet was actually taken to the photocopier. */
export const markSheetPrinted = (sheetId: Uuid) =>
  apiRequest<SheetOut>(`/sheets/${sheetId}/printed`, { method: 'POST' });

/* ----------------------------------------------------------- timeline --- */
export const getTimeline = (query: TimelineQuery = {}) =>
  apiRequest<TimelineOut>('/timeline', {
    query: {
      kind: query.kind,
      subject_id: query.subject_id,
      since: query.since,
      until: query.until,
      q: query.q,
      offset: query.offset,
      limit: query.limit,
    },
  });

/* --------------------------------------------------------------- jobs --- */
export const getJob = (jobId: Uuid) => apiRequest<JobOut>(`/jobs/${jobId}`);
