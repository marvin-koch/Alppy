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
  AdaptiveBatchRequest,
  AdaptiveProposeRequest,
  AdaptiveProposeResponse,
  ChapterOut,
  ClassOut,
  CurriculumKind,
  DetectionCorrection,
  DetectionOut,
  ExerciseOut,
  ExerciseUpdate,
  HomeOut,
  JobOut,
  MasteryMatrixOut,
  ScanConfirmResponse,
  ScanOut,
  ScanPageOut,
  SheetCreate,
  SheetOut,
  SheetProposeRequest,
  SheetProposeResponse,
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
  classMastery: (id: Uuid, subjectId?: Uuid) => ['classes', id, 'mastery', subjectId ?? null] as const,
  studentMastery: (id: Uuid) => ['students', id, 'mastery'] as const,
  subjects: ['subjects'] as const,
  chapters: (subjectId?: Uuid) => ['chapters', subjectId ?? null] as const,
  competencies: (kind: CurriculumKind, subjectKey?: string) =>
    ['competencies', kind, subjectKey ?? null] as const,
  sources: ['sources'] as const,
  source: (id: Uuid) => ['sources', id] as const,
  sourceExercises: (id: Uuid) => ['sources', id, 'exercises'] as const,
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
      void client.invalidateQueries({ queryKey: queryKeys.home });
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
export function useClasses(): UseQueryResult<ClassOut[]> {
  return useQuery({ queryKey: queryKeys.classes, queryFn: api.listClasses });
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

export function useSubjects(): UseQueryResult<SubjectOut[]> {
  return useQuery({ queryKey: queryKeys.subjects, queryFn: api.listSubjects });
}

export function useChapters(subjectId?: Uuid): UseQueryResult<ChapterOut[]> {
  return useQuery({
    queryKey: queryKeys.chapters(subjectId),
    queryFn: () => api.listChapters(subjectId),
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
  subjectId?: Uuid,
): UseQueryResult<MasteryMatrixOut> {
  return useQuery({
    queryKey: queryKeys.classMastery(classId ?? '', subjectId),
    queryFn: () => api.getClassMastery(classId as Uuid, subjectId),
    enabled: Boolean(classId),
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

export function useUploadSource(): UseMutationResult<SourceOut | JobOut, Error, File> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.uploadSource,
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.sources }),
  });
}

/* ------------------------------------------------------------- sheets --- */
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
export function useScan(scanId: Uuid | null): UseQueryResult<ScanOut> {
  return useQuery({
    queryKey: queryKeys.scan(scanId ?? ''),
    queryFn: () => api.getScan(scanId as Uuid),
    enabled: Boolean(scanId),
  });
}

export function useUploadScan(): UseMutationResult<
  ScanOut | JobOut,
  Error,
  { files: File[]; sheetId?: Uuid }
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

export function useConfirmScan(
  scanId: Uuid | null,
): UseMutationResult<ScanConfirmResponse, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.confirmScan(scanId as Uuid),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.scan(scanId ?? '') });
      void client.invalidateQueries({ queryKey: queryKeys.home });
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

export function useBatchAdaptive(): UseMutationResult<JobOut, Error, AdaptiveBatchRequest> {
  return useMutation({ mutationFn: api.batchAdaptive });
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
