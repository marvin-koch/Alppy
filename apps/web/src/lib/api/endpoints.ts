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
  ClassTeacherOut,
  ColleagueOut,
  ClassPointsOut,
  CompetencyAttemptsOut,
  CompetencyOut,
  CurriculumKind,
  DetectionCorrection,
  DetectionOut,
  ExerciseCreate,
  ExerciseBankQuery,
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
  SchoolOut,
  SchoolYearOut,
  LocalisedText,
  SourceOut,
  SourceSectionOut,
  StudentExportOut,
  StudentOut,
  SheetMasteryOut,
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
 * Every path below is checked against the routes the API actually serves by
 * `apps/web/src/lib/api/__tests__/contract.test.ts`, which reads this file and
 * `@alppy/shared/api-routes` — generated from the routers, so it cannot drift.
 * Guessing at "the obvious path" is how `POST /scans/{id}/pages/{id}/assign`
 * came to be called for two milestones against an API that only ever exposed
 * `PATCH …/pages/{id}`. The test checks the address, not the method: a wrong
 * method is a 405 on the first click, a wrong path can hide for a milestone.
 */

/* --------------------------------------------------------------- auth --- */
export const login = (body: LoginRequest) =>
  apiRequest<TeacherOut>('/auth/login', { method: 'POST', body });

export const logout = () => apiRequest<void>('/auth/logout', { method: 'POST' });

export const getMe = () => apiRequest<TeacherOut>('/auth/me');

/* ------------------------------------------------- the editable nouns --- */
export const createSubject = (body: { key: string; labels: LocalisedText }) =>
  apiRequest<SubjectOut>('/subjects', { method: 'POST', body });

export const updateSubject = (id: Uuid, body: { labels: LocalisedText }) =>
  apiRequest<SubjectOut>(`/subjects/${id}`, { method: 'PATCH', body });

export const updateClass = (id: Uuid, body: { label?: string | null; code?: string }) =>
  apiRequest<ClassOut>(`/classes/${id}`, { method: 'PATCH', body });

export const updateSchool = (body: { name?: string; canton?: string | null }) =>
  apiRequest<SchoolOut>('/schools/me', { method: 'PATCH', body });

export const updateStudent = (
  id: Uuid,
  body: { first_name?: string; last_name?: string },
) => apiRequest<StudentOut>(`/students/${id}`, { method: 'PATCH', body });

/** Takes the pupil's own uid, typed back — see `ConfirmDestructive`. */
export const deleteStudent = (id: Uuid, confirm: string) =>
  apiRequest<void>(`/students/${id}`, { method: 'DELETE', query: { confirm } });

export const updateChapter = (
  id: Uuid,
  body: { labels?: LocalisedText; position?: number; competency_ids?: Uuid[] },
) => apiRequest<ChapterOut>(`/chapters/${id}`, { method: 'PATCH', body });

export const deleteChapter = (id: Uuid) =>
  apiRequest<void>(`/chapters/${id}`, { method: 'DELETE' });

export const updateSource = (
  id: Uuid,
  body: { title?: string; language?: string; publisher?: string; isbn?: string; url?: string },
) =>
  apiRequest<SourceOut>(`/sources/${id}`, { method: 'PATCH', body });

export const deleteSource = (id: Uuid) =>
  apiRequest<void>(`/sources/${id}`, { method: 'DELETE' });

/**
 * Act for another of this teacher's schools from here on.
 *
 * The server re-issues the session cookie, so everything after this request
 * is already scoped to the new tenant — there is nothing for the client to
 * carry. Callers must drop every cached query afterwards: the ids in them
 * belong to the school we just left.
 */
export const switchSchool = (schoolId: Uuid) =>
  apiRequest<TeacherOut>(`/auth/school/${schoolId}`, { method: 'POST' });

export const updatePreferences = (body: Partial<TeacherPreferences>) =>
  apiRequest<TeacherOut>('/teachers/me/preferences', { method: 'PATCH', body });

/* --------------------------------------------------------------- home --- */
export const getHome = (schoolYearId?: Uuid) =>
  apiRequest<HomeOut>('/home', { query: { school_year_id: schoolYearId } });

/* ------------------------------------------------- the school's years --- */
/**
 * The years this establishment has run, newest first.
 *
 * The discovery route for every `school_year_id` filter below: an id has to
 * come from somewhere, and a client cannot guess one.
 */
export const listSchoolYears = () => apiRequest<SchoolYearOut[]>('/school-years');

/* ------------------------------------------------------------ classes --- */
export const listClasses = (schoolYearId?: Uuid) =>
  apiRequest<ClassOut[]>('/classes', { query: { school_year_id: schoolYearId } });

export const createClass = (body: ClassCreate) =>
  apiRequest<ClassOut>('/classes', { method: 'POST', body });

export const getClass = (classId: Uuid) => apiRequest<ClassOut>(`/classes/${classId}`);

export const addStudents = (classId: Uuid, body: RosterCreate) =>
  apiRequest<StudentOut[]>(`/classes/${classId}/students`, { method: 'POST', body });

/**
 * Who sits in this class. `on` (an ISO date) reads the roster as it stood that
 * day instead of today — the enrolment rows are time-bound, so the group that
 * sat a sheet in October is not necessarily the group sitting there now.
 */
export const listStudents = (classId: Uuid, on?: string) =>
  apiRequest<StudentOut[]>(`/classes/${classId}/students`, { query: { on } });

export const createRoster = (classId: Uuid, body: RosterCreate) =>
  apiRequest<StudentOut[]>(`/classes/${classId}/students`, { method: 'POST', body });

/**
 * Everything the school holds about one pupil, in one document.
 *
 * A parent may ask, and a school leaving Alppy has to be able to take it. It
 * spans every year: `Person` is the durable identity and a `Student` row is
 * one year's enrolment, so a pupil who repeated has two enrolments and one
 * continuous record behind them.
 */
export const exportStudent = (studentId: Uuid) =>
  apiRequest<StudentExportOut>(`/students/${studentId}/export`);

/** Seat an existing pupil in another of this teacher's classes. Idempotent,
 *  and it never touches their uid — that came from their home class (D69). */
export const enrollStudent = (classId: Uuid, studentId: Uuid) =>
  apiRequest<StudentOut[]>(`/classes/${classId}/students/${studentId}/enrollment`, {
    method: 'POST',
  });

/** Remove a pupil from a class without deleting them. Refused on their home. */
export const unenrollStudent = (classId: Uuid, studentId: Uuid) =>
  apiRequest<StudentOut[]>(`/classes/${classId}/students/${studentId}/enrollment`, {
    method: 'DELETE',
  });

/* ---------------------------------------------- who teaches what (D75) --- */
/**
 * Two different questions, and the paths keep them apart.
 *
 * `/classes/{id}/teachers/.../branches/...` is who TEACHES a branch here;
 * `/classes/{id}/subjects` is what the class STUDIES. Declaring a branch also
 * assigns it to the caller server-side, so the two are never out of step for
 * the person who just declared one.
 *
 * Each returns the list the caller wanted rather than the row it wrote, so a
 * screen never has to guess what the write did to the rest of the set.
 */
export const listClassTeachers = (classId: Uuid) =>
  apiRequest<ClassTeacherOut[]>(`/classes/${classId}/teachers`);

export const listColleagues = () => apiRequest<ColleagueOut[]>('/colleagues');

export const assignBranch = (classId: Uuid, teacherId: Uuid, subjectId: Uuid) =>
  apiRequest<ClassTeacherOut[]>(
    `/classes/${classId}/teachers/${teacherId}/branches/${subjectId}`,
    { method: 'POST' },
  );

export const unassignBranch = (classId: Uuid, teacherId: Uuid, subjectId: Uuid) =>
  apiRequest<ClassTeacherOut[]>(
    `/classes/${classId}/teachers/${teacherId}/branches/${subjectId}`,
    { method: 'DELETE' },
  );

/** Say the class studies this branch — and that the caller takes it. */
export const declareBranch = (classId: Uuid, subjectId: Uuid) =>
  apiRequest<ClassOut>(`/classes/${classId}/subjects/${subjectId}`, { method: 'POST' });

/** Refused with a `sheet_count` while the branch still holds sheets here. */
export const undeclareBranch = (classId: Uuid, subjectId: Uuid) =>
  apiRequest<ClassOut>(`/classes/${classId}/subjects/${subjectId}`, { method: 'DELETE' });

/**
 * Set the branch nav order. Takes the WHOLE list, because the order belongs to
 * the class: a partial update from one co-teacher must not renumber another's.
 */
export const reorderBranches = (classId: Uuid, subjectIds: Uuid[]) =>
  apiRequest<ClassOut>(`/classes/${classId}/subjects`, {
    method: 'PUT',
    body: { subject_ids: subjectIds },
  });

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
/**
 * The bank: the school's whole corpus, filtered, without naming a document.
 *
 * `listSourceExercises` above is the document browser and stays as it is —
 * this shares its query and its facet block rather than replacing it. The two
 * differ in what they can be asked: a source is one book, the bank is
 * everything, including the exercises a teacher wrote themselves, which have
 * no source to be browsed from at all.
 */
export const listExercises = (query: ExerciseBankQuery = {}) =>
  apiRequest<ExerciseListOut>('/exercises', { query: { ...query } });

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
export const listSheets = (classId?: Uuid, subjectId?: Uuid, schoolYearId?: Uuid) =>
  apiRequest<SheetOut[]>('/sheets', {
    query: { class_id: classId, subject_id: subjectId, school_year_id: schoolYearId },
  });

export const listScans = (sheetId?: Uuid, schoolYearId?: Uuid) =>
  apiRequest<ScanOut[]>('/scans', {
    query: { sheet_id: sheetId, school_year_id: schoolYearId },
  });

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

/**
 * Who this scan's pages may be assigned to: the sheet's own class, nobody else.
 *
 * The server reads that roster as of the day the SHEET was made, which is the
 * right guess. `on` overrides it when the guess is wrong — composed in
 * September, sat in November, by a group that changed in between.
 */
export const listScanStudents = (scanId: Uuid, on?: string) =>
  apiRequest<StudentOut[]>(`/scans/${scanId}/students`, { query: { on } });

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
  options: { subjectId?: Uuid; chapterId?: Uuid; asOf?: string } = {},
) =>
  apiRequest<ClassPointsOut>(`/classes/${classId}/points`, {
    query: {
      subject_id: options.subjectId,
      chapter_id: options.chapterId,
      as_of: options.asOf,
    },
  });

export const getStudentSheet = (studentId: Uuid, sheetId: Uuid, asOf?: string) =>
  apiRequest<StudentSheetOut>(`/students/${studentId}/sheets/${sheetId}`, {
    query: { as_of: asOf },
  });

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
  options: { subjectId?: Uuid; studentId?: Uuid; asOf?: string } = {},
) =>
  apiRequest<ClassTreeOut>(`/classes/${classId}/tree`, {
    query: {
      subject_id: options.subjectId,
      student_id: options.studentId,
      as_of: options.asOf,
    },
  });

export const getClassMastery = (
  classId: Uuid,
  options: { subjectId?: Uuid; chapterId?: Uuid; sort?: MatrixSort; asOf?: string } = {},
) =>
  apiRequest<MasteryMatrixOut>(`/classes/${classId}/mastery`, {
    query: {
      subject_id: options.subjectId,
      chapter_id: options.chapterId,
      // An ISO instant. The matrix computed as it stood then — the roster
      // moves with it, so this is October's group and not today's.
      as_of: options.asOf,
      // 'roster' is the server default; omitting it keeps the URL (and the
      // react-query key) stable for the unfiltered case.
      sort: options.sort === 'weakest' ? 'weakest' : undefined,
    },
  });

/** One sheet's band per pupil, plus the class roll-up. Works unchanged on an
 *  adaptive batch: `Sheet.target` never enters the arithmetic (D72). */
export const getSheetMastery = (sheetId: Uuid, asOf?: string) =>
  apiRequest<SheetMasteryOut>(`/sheets/${sheetId}/mastery`, { query: { as_of: asOf } });

export const getStudentMastery = (studentId: Uuid, asOf?: string) =>
  apiRequest<StudentProfileOut>(`/students/${studentId}/mastery`, {
    query: { as_of: asOf },
  });

export const getCompetencyAttempts = (
  studentId: Uuid,
  competencyId: Uuid,
  asOf?: string,
) =>
  apiRequest<CompetencyAttemptsOut>(
    `/students/${studentId}/competencies/${competencyId}/attempts`,
    { query: { as_of: asOf } },
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
