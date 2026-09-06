import { apiRequest } from './client';
import type {
  AdaptiveBatchRequest,
  AdaptiveProposeRequest,
  AdaptiveProposeResponse,
  ChapterOut,
  ClassCreate,
  ClassOut,
  CompetencyOut,
  CurriculumKind,
  DetectionCorrection,
  DetectionOut,
  ExerciseOut,
  ExerciseUpdate,
  HomeOut,
  JobOut,
  LoginRequest,
  MasteryMatrixOut,
  RosterCreate,
  ScanConfirmResponse,
  ScanOut,
  ScanPageAssign,
  ScanPageOut,
  SheetCreate,
  SheetOut,
  SheetProposeRequest,
  SheetProposeResponse,
  SheetUpdate,
  SourceOut,
  StudentOut,
  StudentProfileOut,
  SubjectOut,
  TeacherOut,
  TeacherPreferences,
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
 *   · `POST /scans/{id}/pages/{pageId}/assign` (ScanPageAssign has no route)
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

export const listSourceExercises = (sourceId: Uuid) =>
  apiRequest<ExerciseOut[]>(`/sources/${sourceId}/exercises`);

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

/* ------------------------------------------------------------- sheets --- */
export const proposeSheet = (body: SheetProposeRequest) =>
  apiRequest<SheetProposeResponse>('/sheets/propose', { method: 'POST', body });

export const createSheet = (body: SheetCreate) =>
  apiRequest<SheetOut>('/sheets', { method: 'POST', body });

export const updateSheet = (sheetId: Uuid, body: SheetUpdate) =>
  apiRequest<SheetOut>(`/sheets/${sheetId}`, { method: 'PATCH', body });

export const getSheet = (sheetId: Uuid) => apiRequest<SheetOut>(`/sheets/${sheetId}`);

/** Every sheet the teacher has built. Without this a sheet was reachable only
 *  by the redirect that follows creating it. */
export const listSheets = () => apiRequest<SheetOut[]>('/sheets');

export const renderSheet = (sheetId: Uuid) =>
  apiRequest<JobOut>(`/sheets/${sheetId}/render`, { method: 'POST' });

/* -------------------------------------------------------------- scans --- */
export const uploadScan = (files: File[], sheetId?: Uuid) => {
  const formData = new FormData();
  for (const file of files) formData.append('files', file);
  if (sheetId) formData.append('sheet_id', sheetId);
  return apiRequest<ScanOut | JobOut>('/scans', { method: 'POST', formData });
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
  apiRequest<ScanPageOut>(`/scans/${scanId}/pages/${pageId}/assign`, { method: 'POST', body });

export const confirmScan = (scanId: Uuid) =>
  apiRequest<ScanConfirmResponse>(`/scans/${scanId}/confirm`, { method: 'POST' });

/* ------------------------------------------------------------ mastery --- */
export const getClassMastery = (classId: Uuid, subjectId?: Uuid) =>
  apiRequest<MasteryMatrixOut>(`/classes/${classId}/mastery`, {
    query: { subject_id: subjectId },
  });

export const getStudentMastery = (studentId: Uuid) =>
  apiRequest<StudentProfileOut>(`/students/${studentId}/mastery`);

/* ----------------------------------------------------------- adaptive --- */
export const proposeAdaptive = (body: AdaptiveProposeRequest) =>
  apiRequest<AdaptiveProposeResponse>('/adaptive/propose', { method: 'POST', body });

export const batchAdaptive = (body: AdaptiveBatchRequest) =>
  apiRequest<JobOut>('/adaptive/batch', { method: 'POST', body });

/* --------------------------------------------------------------- jobs --- */
export const getJob = (jobId: Uuid) => apiRequest<JobOut>(`/jobs/${jobId}`);
