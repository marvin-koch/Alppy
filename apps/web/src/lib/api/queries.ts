'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import * as api from './endpoints';
import type {
  AdaptiveApproveRequest,
  AdaptiveApproveResponse,
  AdaptiveBatchRequest,
  AdaptiveDiscardRequest,
  AdaptiveDiscardResponse,
  AdaptiveRegenerateRequest,
  AdaptiveRegenerateResponse,
  AdaptiveProposeRequest,
  AdaptiveProposeResponse,
  ChapterOut,
  ClassCreate,
  ClassOut,
  CompetencyAttemptsOut,
  CurriculumKind,
  DetectionCorrection,
  DetectionOut,
  ExerciseOut,
  ExerciseUpdate,
  HomeOut,
  JobOut,
  MasteryMatrixOut,
  MatrixSort,
  ScanConfirmResponse,
  ScanOut,
  ScanPageOut,
  SheetCreate,
  SheetOut,
  SheetProposeRequest,
  SheetProposeResponse,
  RosterCreate,
  SourceOut,
  StudentOut,
  StudentProfileOut,
  SubjectOut,
  TeacherOut,
  TeacherPreferences,
  Uuid,
} from './types';
import { isTerminal } from './types';

/** One place where every cache key is spelled, so invalidation is never guessed. */
export const queryKeys = {
  me: ['me'] as const,
  home: ['home'] as const,
  classes: ['classes'] as const,
  klass: (id: Uuid) => ['classes', id] as const,
  students: (id: Uuid) => ['classes', id, 'students'] as const,
  // The prefix ['classes', id, 'mastery'] is what confirming a scan
  // invalidates, so every filter/sort variant has to hang off it.
  classMastery: (id: Uuid, options: { subjectId?: Uuid; chapterId?: Uuid; sort?: MatrixSort } = {}) =>
    [
      'classes',
      id,
      'mastery',
      options.subjectId ?? null,
      options.chapterId ?? null,
      options.sort ?? 'roster',
    ] as const,
  studentMastery: (id: Uuid) => ['students', id, 'mastery'] as const,
  competencyAttempts: (studentId: Uuid, competencyId: Uuid) =>
    ['students', studentId, 'mastery', 'attempts', competencyId] as const,
  subjects: ['subjects'] as const,
  chapters: (subjectId?: Uuid) => ['chapters', subjectId ?? null] as const,
  competencies: (kind: CurriculumKind, subjectKey?: string) =>
    ['competencies', kind, subjectKey ?? null] as const,
  sources: ['sources'] as const,
  source: (id: Uuid) => ['sources', id] as const,
  sourceExercises: (id: Uuid) => ['sources', id, 'exercises'] as const,
  sheets: (classId?: Uuid) => ['sheets', classId ?? null] as const,
  scans: (sheetId?: Uuid) => ['scans', sheetId ?? null] as const,
  sheet: (id: Uuid) => ['sheets', id] as const,
  scan: (id: Uuid) => ['scans', id] as const,
  detections: (id: Uuid) => ['scans', id, 'detections'] as const,
  job: (id: Uuid) => ['jobs', id] as const,
};

/* --------------------------------------------------------------- auth --- */
export function useMe(): UseQueryResult<TeacherOut> {
  return useQuery({ queryKey: queryKeys.me, queryFn: api.getMe, retry: false });
}

export function useLogin(): UseMutationResult<TeacherOut, Error, { email: string; password: string }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.login,
    onSuccess: (teacher) => {
      client.setQueryData(queryKeys.me, teacher);
      // Everything, not just `home`. Queries that ran while logged out failed
      // with a 401 and are never retried (`retry` returns false for 401), so
      // invalidating one key left the rest of the cache holding stale errors —
      // which is why the class/subject switcher came up empty right after a
      // successful login.
      void client.invalidateQueries();
    },
  });
}

export function useLogout(): UseMutationResult<void, Error, void> {
  const client = useQueryClient();
  return useMutation({ mutationFn: api.logout, onSuccess: () => client.clear() });
}

export function useUpdatePreferences(): UseMutationResult<
  TeacherOut,
  Error,
  Partial<TeacherPreferences>
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.updatePreferences,
    onSuccess: (teacher) => client.setQueryData(queryKeys.me, teacher),
  });
}

/* --------------------------------------------------------------- home --- */
export function useHome(): UseQueryResult<HomeOut> {
  return useQuery({ queryKey: queryKeys.home, queryFn: api.getHome });
}

/* ------------------------------------------------------------ classes --- */
export function useClasses(enabled = true): UseQueryResult<ClassOut[]> {
  return useQuery({ queryKey: queryKeys.classes, queryFn: api.listClasses, enabled });
}

export function useCreateClass(): UseMutationResult<ClassOut, Error, ClassCreate> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.createClass,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.classes });
      void client.invalidateQueries({ queryKey: queryKeys.home });
    },
  });
}

export function useAddStudents(): UseMutationResult<
  StudentOut[],
  Error,
  { classId: Uuid; body: RosterCreate }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ classId, body }) => api.addStudents(classId, body),
    onSuccess: (_data, { classId }) => {
      void client.invalidateQueries({ queryKey: queryKeys.students(classId) });
      void client.invalidateQueries({ queryKey: queryKeys.klass(classId) });
      void client.invalidateQueries({ queryKey: queryKeys.classes });
      void client.invalidateQueries({ queryKey: queryKeys.home });
    },
  });
}

export function useClass(classId: Uuid | null): UseQueryResult<ClassOut> {
  return useQuery({
    queryKey: queryKeys.klass(classId ?? ''),
    queryFn: () => api.getClass(classId as Uuid),
    enabled: Boolean(classId),
  });
}

export function useStudents(classId: Uuid | null): UseQueryResult<StudentOut[]> {
  return useQuery({
    queryKey: queryKeys.students(classId ?? ''),
    queryFn: () => api.listStudents(classId as Uuid),
    enabled: Boolean(classId),
  });
}

export function useSubjects(enabled = true): UseQueryResult<SubjectOut[]> {
  return useQuery({ queryKey: queryKeys.subjects, queryFn: api.listSubjects, enabled });
}

export function useChapters(subjectId?: Uuid): UseQueryResult<ChapterOut[]> {
  return useQuery({
    queryKey: queryKeys.chapters(subjectId),
    queryFn: () => api.listChapters(subjectId),
    // No subject means no chapter list. Asking anyway dropped the parameter and
    // returned EVERY chapter in the school, so a class with no sheets yet
    // offered a filter full of chapters it had never been taught.
    enabled: Boolean(subjectId),
  });
}

export function useCreateRoster(
  classId: Uuid | null,
): UseMutationResult<StudentOut[], Error, { students: Array<{ first_name: string; last_name: string }> }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { students: Array<{ first_name: string; last_name: string }> }) =>
      api.createRoster(classId as Uuid, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.students(classId ?? '') });
      void client.invalidateQueries({ queryKey: queryKeys.home });
    },
  });
}

/* ------------------------------------------------------------ mastery --- */
export function useClassMastery(
  classId: Uuid | null,
  options: { subjectId?: Uuid; chapterId?: Uuid; sort?: MatrixSort } = {},
): UseQueryResult<MasteryMatrixOut> {
  return useQuery({
    queryKey: queryKeys.classMastery(classId ?? '', options),
    queryFn: () => api.getClassMastery(classId as Uuid, options),
    enabled: Boolean(classId),
  });
}

export function useCompetencyAttempts(
  studentId: Uuid | null,
  competencyId: Uuid | null,
): UseQueryResult<CompetencyAttemptsOut> {
  return useQuery({
    queryKey: queryKeys.competencyAttempts(studentId ?? '', competencyId ?? ''),
    queryFn: () => api.getCompetencyAttempts(studentId as Uuid, competencyId as Uuid),
    enabled: Boolean(studentId && competencyId),
  });
}

export function useStudentMastery(studentId: Uuid | null): UseQueryResult<StudentProfileOut> {
  return useQuery({
    queryKey: queryKeys.studentMastery(studentId ?? ''),
    queryFn: () => api.getStudentMastery(studentId as Uuid),
    enabled: Boolean(studentId),
  });
}

/* ------------------------------------------------------------ sources --- */
export function useSources(): UseQueryResult<SourceOut[]> {
  return useQuery({ queryKey: queryKeys.sources, queryFn: api.listSources });
}

export function useSourceExercises(sourceId: Uuid | null): UseQueryResult<ExerciseOut[]> {
  return useQuery({
    queryKey: queryKeys.sourceExercises(sourceId ?? ''),
    queryFn: () => api.listSourceExercises(sourceId as Uuid),
    enabled: Boolean(sourceId),
  });
}

export function useUploadSource(): UseMutationResult<
  SourceOut | JobOut,
  Error,
  { file: File; subjectId: Uuid }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.uploadSource,
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.sources }),
  });
}

/* ------------------------------------------------------------- sheets --- */
export function useSheets(classId?: Uuid): UseQueryResult<SheetOut[]> {
  return useQuery({
    queryKey: queryKeys.sheets(classId),
    queryFn: () => api.listSheets(classId),
  });
}

/* -------------------------------------------------------------- scans --- */
export function useScans(sheetId?: Uuid): UseQueryResult<ScanOut[]> {
  return useQuery({
    queryKey: queryKeys.scans(sheetId),
    queryFn: () => api.listScans(sheetId),
  });
}

export function useSheet(sheetId: Uuid | null): UseQueryResult<SheetOut> {
  return useQuery({
    queryKey: queryKeys.sheet(sheetId ?? ''),
    queryFn: () => api.getSheet(sheetId as Uuid),
    enabled: Boolean(sheetId),
  });
}

export function useProposeSheet(): UseMutationResult<
  SheetProposeResponse,
  Error,
  SheetProposeRequest
> {
  return useMutation({ mutationFn: api.proposeSheet });
}

export function useCreateSheet(): UseMutationResult<SheetOut, Error, SheetCreate> {
  return useMutation({ mutationFn: api.createSheet });
}

export function useRenderSheet(): UseMutationResult<JobOut, Error, Uuid> {
  return useMutation({ mutationFn: api.renderSheet });
}

export function useUpdateExercise(): UseMutationResult<
  ExerciseOut,
  Error,
  { exerciseId: Uuid; update: ExerciseUpdate }
> {
  return useMutation({
    mutationFn: ({ exerciseId, update }) => api.updateExercise(exerciseId, update),
  });
}

/* -------------------------------------------------------------- scans --- */
/**
 * One scan, polled while the worker is still reading it.
 *
 * Without the interval the teacher lands on the review screen straight after
 * uploading, sees `status: "uploaded"` with no pages — indistinguishable from a
 * finished empty scan, Confirm enabled — and it never changes until they think
 * to reload. Polling stops the moment the scan reaches a terminal state.
 */
export function useScan(scanId: Uuid | null): UseQueryResult<ScanOut> {
  return useQuery({
    queryKey: queryKeys.scan(scanId ?? ''),
    queryFn: () => api.getScan(scanId as Uuid),
    enabled: Boolean(scanId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'uploaded' || status === 'processing' ? 1000 : false;
    },
  });
}

/** Who this scan's pages may be assigned to: the sheet's class, nobody else. */
export function useScanStudents(scanId: Uuid | null): UseQueryResult<StudentOut[]> {
  return useQuery({
    queryKey: [...queryKeys.scan(scanId ?? ''), 'students'],
    queryFn: () => api.listScanStudents(scanId as Uuid),
    enabled: Boolean(scanId),
  });
}

export function useUploadScan(): UseMutationResult<
  ScanOut,
  Error,
  { files: File[]; sheetId: Uuid }
> {
  return useMutation({ mutationFn: ({ files, sheetId }) => api.uploadScan(files, sheetId) });
}

export function useCorrectDetection(
  scanId: Uuid | null,
): UseMutationResult<DetectionOut, Error, { detectionId: Uuid; body: DetectionCorrection }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ detectionId, body }) => api.correctDetection(scanId as Uuid, detectionId, body),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.scan(scanId ?? '') }),
  });
}

export function useAssignScanPage(
  scanId: Uuid | null,
): UseMutationResult<ScanPageOut, Error, { pageId: Uuid; studentId: Uuid }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ pageId, studentId }) =>
      api.assignScanPage(scanId as Uuid, pageId, { student_id: studentId }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.scan(scanId ?? '') }),
  });
}

export function useDiscardScanPage(
  scanId: Uuid | null,
): UseMutationResult<ScanPageOut, Error, { pageId: Uuid; discarded: boolean }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ pageId, discarded }) =>
      api.discardScanPage(scanId as Uuid, pageId, { discarded }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.scan(scanId ?? '') }),
  });
}

export function useConfirmScan(
  scanId: Uuid | null,
): UseMutationResult<ScanConfirmResponse, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.confirmScan(scanId as Uuid),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.scan(scanId ?? '') });
      void client.invalidateQueries({ queryKey: queryKeys.home });
      // Confirming is the moment the matrix changes. Without these two the
      // teacher walks from the review screen back to the grid and, for the
      // 30s staleTime, sees the numbers from before they confirmed. The
      // prefixes cover every class and every student, which is right: a pile
      // of copies can carry more than one class's worth of paper.
      void client.invalidateQueries({ queryKey: ['classes'] });
      void client.invalidateQueries({ queryKey: ['students'] });
    },
  });
}

/* ----------------------------------------------------------- adaptive --- */
export function useProposeAdaptive(): UseMutationResult<
  AdaptiveProposeResponse,
  Error,
  AdaptiveProposeRequest
> {
  return useMutation({ mutationFn: api.proposeAdaptive });
}

/**
 * Creates the sheet. It does NOT render it — `useRenderAdaptiveBatch` starts
 * the job, and the caller chains the two. Two steps because binding 28 students
 * to their item lists is fast and synchronous, while driving a headless browser
 * over 170 pages is not.
 */
export function useBatchAdaptive(): UseMutationResult<SheetOut, Error, AdaptiveBatchRequest> {
  return useMutation({ mutationFn: api.batchAdaptive });
}

export function useRenderAdaptiveBatch(): UseMutationResult<JobOut, Error, Uuid> {
  return useMutation({ mutationFn: api.renderAdaptiveBatch });
}

export function useApproveAdaptive(): UseMutationResult<
  AdaptiveApproveResponse,
  Error,
  AdaptiveApproveRequest
> {
  return useMutation({ mutationFn: api.approveAdaptive });
}

export function useDiscardAdaptive(): UseMutationResult<
  AdaptiveDiscardResponse,
  Error,
  AdaptiveDiscardRequest
> {
  return useMutation({ mutationFn: api.discardAdaptive });
}

export function useRegenerateAdaptive(): UseMutationResult<
  AdaptiveRegenerateResponse,
  Error,
  AdaptiveRegenerateRequest
> {
  return useMutation({ mutationFn: api.regenerateAdaptive });
}

/* --------------------------------------------------------------- jobs --- */
/**
 * Long work reports real progress: ingestion, PDF render, scan processing and
 * the adaptive batch all go through `GET /jobs/{id}`. Polling stops the moment
 * the job is terminal — a finished job is never re-fetched on a timer.
 */
export function useJob(jobId: Uuid | null): UseQueryResult<JobOut> {
  return useQuery({
    queryKey: queryKeys.job(jobId ?? ''),
    queryFn: () => api.getJob(jobId as Uuid),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && isTerminal(status) ? false : 900;
    },
  });
}
