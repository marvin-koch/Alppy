'use client';

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import * as api from './endpoints';
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
  MasteryMatrixOut,
  MatrixSort,
  MisconceptionNoteOut,
  RosterCreate,
  ScanConfirmResponse,
  ScanOut,
  ScanPageOut,
  ScanUnvalidateResponse,
  SheetConfidenceOut,
  SheetCreate,
  SheetOut,
  SheetProposeRequest,
  SheetProposeResponse,
  LocalisedText,
  SchoolOut,
  SourceOut,
  SourceSectionOut,
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
import { isTerminal } from './types';

/** How many exercises one page of the picker asks for.
 *
 *  Small on purpose. A textbook chapter holds a couple of hundred, the teacher
 *  is choosing perhaps a dozen, and every row carries a full statement plus its
 *  options. */
export const DEFAULT_PAGE_SIZE = 20;

/** One place where every cache key is spelled, so invalidation is never guessed. */
export const queryKeys = {
  me: ['me'] as const,
  feedback: (sourceSheetId: Uuid) => ['feedback', sourceSheetId] as const,
  // Every filter variant is spelled into the key, so invalidation never has to
  // guess which page a change affects.
  timeline: (q: TimelineQuery) =>
    [
      'timeline',
      (q.kind ?? []).join(','),
      q.subject_id ?? '',
      q.since ?? '',
      q.until ?? '',
      q.q ?? '',
      q.offset ?? 0,
      q.limit ?? DEFAULT_PAGE_SIZE,
    ] as const,
  adaptiveProposal: (jobId: Uuid) => ['adaptive', 'proposal', jobId] as const,
  home: ['home'] as const,
  classes: ['classes'] as const,
  klass: (id: Uuid) => ['classes', id] as const,
  students: (id: Uuid) => ['classes', id, 'students'] as const,
  // The prefix ['classes', id, 'mastery'] is what confirming a scan
  // invalidates, so every filter/sort variant has to hang off it.
  classPoints: (id: Uuid, options: { subjectId?: Uuid; chapterId?: Uuid } = {}) =>
    ['classes', id, 'points', options.subjectId ?? null, options.chapterId ?? null] as const,
  sheetConfidence: (id: Uuid) => ['sheets', id, 'confidence'] as const,
  studentSheet: (studentId: Uuid, sheetId: Uuid) =>
    ['students', studentId, 'sheets', sheetId] as const,
  classMastery: (id: Uuid, options: { subjectId?: Uuid; chapterId?: Uuid; sort?: MatrixSort } = {}) =>
    [
      'classes',
      id,
      'mastery',
      options.subjectId ?? null,
      options.chapterId ?? null,
      options.sort ?? 'roster',
    ] as const,
  classTree: (id: Uuid, options: { subjectId?: Uuid; studentId?: Uuid } = {}) =>
    ['classes', id, 'tree', options.subjectId ?? null, options.studentId ?? null] as const,
  sheetMastery: (sheetId: Uuid) => ['sheet-mastery', sheetId] as const,
  studentMastery: (id: Uuid) => ['students', id, 'mastery'] as const,
  competencyAttempts: (studentId: Uuid, competencyId: Uuid) =>
    ['students', studentId, 'mastery', 'attempts', competencyId] as const,
  subjects: ['subjects'] as const,
  chapters: (subjectId?: Uuid) => ['chapters', subjectId ?? null] as const,
  competencies: (kind: CurriculumKind, subjectKey?: string) =>
    ['competencies', kind, subjectKey ?? null] as const,
  sources: ['sources'] as const,
  source: (id: Uuid) => ['sources', id] as const,
  sourceSections: (id: Uuid) => ['sources', id, 'sections'] as const,
  // Every filter variant hangs off the ['sources', id, 'exercises'] prefix, so
  // extracting a chapter can invalidate all of them with one call.
  sourceExercises: (id: Uuid, query: ExerciseQuery = {}) =>
    [
      'sources',
      id,
      'exercises',
      query.section_id ?? null,
      query.chapter_id ?? null,
      query.type ?? null,
      query.difficulty ?? null,
      query.q ?? '',
      query.offset ?? 0,
      query.limit ?? DEFAULT_PAGE_SIZE,
    ] as const,
  sheets: (classId?: Uuid, subjectId?: Uuid) =>
    ['sheets', classId ?? null, subjectId ?? null] as const,
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

/**
 * Switch the tenant this session acts for.
 *
 * `invalidateQueries` is not enough and `clear()` is not overkill: after the
 * cookie is re-issued, every cached id in the client belongs to the school we
 * just left. Keeping any of it would render one school's classes under
 * another's name until each query happened to refetch.
 */
/* --------------------------------------------------- editable nouns --- */
export function useUpdateStudent(): UseMutationResult<
  StudentOut,
  Error,
  { studentId: Uuid; classId: Uuid; body: { first_name?: string; last_name?: string } }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ studentId, body }) => api.updateStudent(studentId, body),
    onSuccess: (_data, { classId }) => {
      void client.invalidateQueries({ queryKey: queryKeys.students(classId) });
    },
  });
}

export function useDeleteStudent(): UseMutationResult<
  void,
  Error,
  { studentId: Uuid; classId: Uuid; confirm: string }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ studentId, confirm }) => api.deleteStudent(studentId, confirm),
    // Everything a pupil touched goes with them — the roster, the counts on
    // the class card and the home screen, and every band they contributed to.
    onSuccess: (_data, { classId }) => {
      void client.invalidateQueries({ queryKey: queryKeys.students(classId) });
      void client.invalidateQueries({ queryKey: queryKeys.klass(classId) });
      void client.invalidateQueries({ queryKey: queryKeys.classes });
      void client.invalidateQueries({ queryKey: queryKeys.home });
      void client.invalidateQueries({ queryKey: queryKeys.classMastery(classId, {}) });
    },
  });
}

export function useUpdateClass(): UseMutationResult<
  ClassOut,
  Error,
  { classId: Uuid; body: { label?: string | null; code?: string } }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ classId, body }) => api.updateClass(classId, body),
    onSuccess: (_data, { classId }) => {
      void client.invalidateQueries({ queryKey: queryKeys.klass(classId) });
      void client.invalidateQueries({ queryKey: queryKeys.classes });
      void client.invalidateQueries({ queryKey: queryKeys.home });
    },
  });
}

export function useUpdateSchool(): UseMutationResult<
  SchoolOut,
  Error,
  { name?: string; canton?: string | null }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.updateSchool(body),
    // The school's name rides on `/auth/me`, which is what the rail reads.
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.me }),
  });
}

export function useCreateSubject(): UseMutationResult<
  SubjectOut,
  Error,
  { key: string; labels: LocalisedText }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.createSubject(body),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.subjects }),
  });
}

export function useUpdateSubject(): UseMutationResult<
  SubjectOut,
  Error,
  { subjectId: Uuid; labels: LocalisedText }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ subjectId, labels }) => api.updateSubject(subjectId, { labels }),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.subjects }),
  });
}

export function useSwitchSchool() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (schoolId: Uuid) => api.switchSchool(schoolId),
    onSuccess: () => {
      try {
        window.localStorage.removeItem('alppy.scope');
      } catch {
        // A private window can refuse storage; the scope simply re-resolves.
      }
      queryClient.clear();
    },
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

/* ------------------------------------------------------------ reports --- */
export function useClassPoints(
  classId: Uuid | null,
  options: { subjectId?: Uuid; chapterId?: Uuid } = {},
): UseQueryResult<ClassPointsOut> {
  return useQuery({
    queryKey: queryKeys.classPoints(classId ?? '', options),
    queryFn: () => api.getClassPoints(classId as Uuid, options),
    enabled: Boolean(classId),
  });
}

export function useStudentSheet(
  studentId: Uuid | null,
  sheetId: Uuid | null,
): UseQueryResult<StudentSheetOut> {
  return useQuery({
    queryKey: queryKeys.studentSheet(studentId ?? '', sheetId ?? ''),
    queryFn: () => api.getStudentSheet(studentId as Uuid, sheetId as Uuid),
    enabled: Boolean(studentId && sheetId),
  });
}

export function useSheetConfidence(sheetId: Uuid | null): UseQueryResult<SheetConfidenceOut> {
  return useQuery({
    queryKey: queryKeys.sheetConfidence(sheetId ?? ''),
    queryFn: () => api.getSheetConfidence(sheetId as Uuid),
    enabled: Boolean(sheetId),
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

/**
 * The curriculum tree for one class.
 *
 * `studentId` narrows every band to that child's own attempts — the same
 * computation over a shorter list, not a different rule — which is what lets
 * the student profile group by the same tree the class dashboard shows.
 */
export function useCurriculumTree(
  classId: Uuid | null,
  options: { subjectId?: Uuid; studentId?: Uuid } = {},
): UseQueryResult<ClassTreeOut> {
  return useQuery({
    queryKey: queryKeys.classTree(classId ?? '', options),
    queryFn: () => api.getClassTree(classId as Uuid, options),
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

export function useSheetMastery(sheetId: Uuid | null): UseQueryResult<SheetMasteryOut> {
  return useQuery({
    queryKey: queryKeys.sheetMastery(sheetId ?? ''),
    queryFn: () => api.getSheetMastery(sheetId as Uuid),
    enabled: Boolean(sheetId),
  });
}

/** Seat a pupil in another class. Invalidates every roster-shaped cache: the
 *  matrix, the tree and the home counts all read the enrolled set now. */
export function useEnrollStudent(classId: Uuid | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (studentId: Uuid) => api.enrollStudent(classId as Uuid, studentId),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.students(classId ?? '') });
      void client.invalidateQueries({ queryKey: ['classes'] });
      void client.invalidateQueries({ queryKey: queryKeys.home });
    },
  });
}

export function useUnenrollStudent(classId: Uuid | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (studentId: Uuid) => api.unenrollStudent(classId as Uuid, studentId),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.students(classId ?? '') });
      void client.invalidateQueries({ queryKey: ['classes'] });
      void client.invalidateQueries({ queryKey: queryKeys.home });
    },
  });
}

/* ------------------------------------------------------------ sources --- */
export function useSources(): UseQueryResult<SourceOut[]> {
  return useQuery({ queryKey: queryKeys.sources, queryFn: api.listSources });
}

export function useSourceSections(sourceId: Uuid | null): UseQueryResult<SourceSectionOut[]> {
  return useQuery({
    queryKey: queryKeys.sourceSections(sourceId ?? ''),
    queryFn: () => api.listSourceSections(sourceId as Uuid),
    enabled: Boolean(sourceId),
  });
}

/**
 * One page of a document's exercises.
 *
 * `placeholderData: keepPreviousData` matters here rather than being a nicety:
 * without it, paging or changing a filter empties the list to a skeleton and
 * the checkboxes the teacher just ticked flash away. The selection itself lives
 * in the builder's own state, but the list flickering under it reads as loss.
 */
export function useSourceExercises(
  sourceId: Uuid | null,
  query: ExerciseQuery = {},
): UseQueryResult<ExerciseListOut> {
  return useQuery({
    queryKey: queryKeys.sourceExercises(sourceId ?? '', query),
    queryFn: () => api.listSourceExercises(sourceId as Uuid, query),
    enabled: Boolean(sourceId),
    placeholderData: keepPreviousData,
  });
}

/**
 * Read one chapter on demand.
 *
 * On success both the outline (its `extracted_at` and count change) and every
 * exercise page for the document are stale.
 */
export function useExtractSection(): UseMutationResult<
  JobOut,
  Error,
  { sourceId: Uuid; sectionId: Uuid }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.extractSourceSection,
    onSuccess: (_job, { sourceId }) => {
      void client.invalidateQueries({ queryKey: queryKeys.sourceSections(sourceId) });
      void client.invalidateQueries({ queryKey: ['sources', sourceId, 'exercises'] });
      void client.invalidateQueries({ queryKey: queryKeys.sources });
    },
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
export function useSheets(classId?: Uuid, subjectId?: Uuid): UseQueryResult<SheetOut[]> {
  return useQuery({
    queryKey: queryKeys.sheets(classId, subjectId),
    queryFn: () => api.listSheets(classId, subjectId),
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

/**
 * An exercise the teacher wrote.
 *
 * It is a corpus row, so the document's listing is stale afterwards even though
 * the new exercise carries no `source_id` — the teacher's own items are offered
 * beside the book's, and a list that does not show what you just added reads as
 * a failed save.
 */
export function useCreateExercise(): UseMutationResult<ExerciseOut, Error, ExerciseCreate> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.createExercise,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.sources });
    },
  });
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
      const data = query.state.data;
      const status = data?.status;
      if (status === 'uploaded' || status === 'processing') return 1000;
      // The verdicts on written answers arrive from a chained job after the
      // marks are read; keep looking while any is still pending.
      const reading = data?.pages.some((p) => p.detections.some((d) => d.outcome === 'pending'));
      return reading ? 2000 : false;
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

export function useReopenScan(
  scanId: Uuid | null,
): UseMutationResult<ScanUnvalidateResponse, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.reopenScan(scanId as Uuid),
    onSuccess: () => {
      // Reopening withdraws grades, so it invalidates exactly what confirming
      // does — the same numbers move, in the other direction.
      void client.invalidateQueries({ queryKey: queryKeys.scan(scanId ?? '') });
      void client.invalidateQueries({ queryKey: queryKeys.home });
      void client.invalidateQueries({ queryKey: ['classes'] });
      void client.invalidateQueries({ queryKey: ['students'] });
      void client.invalidateQueries({ queryKey: ['sheets'] });
    },
  });
}

export function useRevertDetection(
  scanId: Uuid | null,
): UseMutationResult<DetectionOut, Error, Uuid> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (detectionId: Uuid) => api.revertDetection(scanId as Uuid, detectionId),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.scan(scanId ?? '') });
    },
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
      // ...and the moment the points dashboard changes, for the same reason.
      void client.invalidateQueries({ queryKey: ['sheets'] });
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
/**
 * Queues the planning and returns the JOB, not the proposal.
 *
 * It used to return the plan directly, which meant every model call for the
 * class ran inside the request handler — a class of twenty-four was
 * twenty-four sequential provider calls with a browser waiting on them.
 * Follow it with `useJob`, then `useAdaptiveProposal`.
 */
export function useProposeAdaptive(): UseMutationResult<
  JobOut,
  Error,
  AdaptiveProposeRequest
> {
  return useMutation({ mutationFn: api.proposeAdaptive });
}

/** The proposal a finished job built. Enabled only once there is a job id. */
export function useAdaptiveProposal(
  jobId: Uuid | null,
): UseQueryResult<AdaptiveProposeResponse> {
  return useQuery({
    queryKey: queryKeys.adaptiveProposal(jobId ?? ''),
    queryFn: () => api.readAdaptiveProposal(jobId as Uuid),
    enabled: jobId != null,
    // A proposal is written once and never changes: refetching it would only
    // re-download a megabyte to learn nothing.
    staleTime: Infinity,
  });
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

/* ------------------------------------------------ misconception notes --- */
/**
 * Every live note written from one common sheet.
 *
 * `writing` is true while the generation job is running, and it turns this into
 * a poll. Without it the notes never appear: generation happens in a worker, so
 * nothing about *this* query changes when the job finishes, and the app's
 * default `staleTime` of 30s with no refetch-on-focus leaves the teacher
 * looking at the empty list the page fetched before they pressed the button.
 */
export function useFeedback(
  sourceSheetId: Uuid | null,
  writing = false,
): UseQueryResult<MisconceptionNoteOut[]> {
  return useQuery({
    queryKey: queryKeys.feedback(sourceSheetId ?? ('none' as Uuid)),
    queryFn: () => api.listFeedback(sourceSheetId as Uuid),
    enabled: sourceSheetId != null,
    refetchInterval: writing ? 1500 : false,
    staleTime: writing ? 0 : undefined,
  });
}

/**
 * Starts the job. One model call per student, so this returns a `JobOut` to
 * poll rather than the notes — the notes are re-read once it succeeds.
 */
export function useGenerateFeedback(): UseMutationResult<JobOut, Error, FeedbackGenerateRequest> {
  return useMutation({ mutationFn: api.generateFeedback });
}

export function useApproveFeedback(): UseMutationResult<
  FeedbackApproveResponse,
  Error,
  FeedbackApproveRequest
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.approveFeedback,
    onSuccess: () => void client.invalidateQueries({ queryKey: ['feedback'] }),
  });
}

export function useDiscardFeedback(): UseMutationResult<
  FeedbackDiscardResponse,
  Error,
  FeedbackDiscardRequest
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.discardFeedback,
    onSuccess: () => void client.invalidateQueries({ queryKey: ['feedback'] }),
  });
}

/**
 * Records the print. Deliberately not awaited by the caller and deliberately
 * not blocking the download: a failed bookkeeping call must never stop a
 * teacher getting their paper.
 */
export function useMarkPrinted(): UseMutationResult<SheetOut, Error, Uuid> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.markSheetPrinted,
    onSuccess: () => void client.invalidateQueries({ queryKey: ['timeline'] }),
  });
}

/* ----------------------------------------------------------- timeline --- */
/**
 * The agenda. `keepPreviousData` so paging or changing a filter does not blank
 * the list under the teacher's cursor — the same choice the exercise listing
 * makes for the same reason.
 */
export function useTimeline(query: TimelineQuery = {}): UseQueryResult<TimelineOut> {
  return useQuery({
    queryKey: queryKeys.timeline(query),
    queryFn: () => api.getTimeline(query),
    placeholderData: (previous) => previous,
  });
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
