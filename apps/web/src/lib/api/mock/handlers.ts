/**
 * The fixture layer. Every screen renders — and every screenshot test runs —
 * without a backend. It answers the same shapes as `alppy/schemas` and raises
 * the same `ApiError` envelope, so nothing downstream knows the difference.
 */
import { ApiError } from '../client';
import type {
  AdaptiveBatchRequest,
  DetectionCorrection,
  ExerciseUpdate,
  JobOut,
  ScanOut,
  SheetCreate,
  SheetOut,
  SourceOut,
  TeacherPreferences,
} from '../types';
import * as fx from './fixtures';

interface MockState {
  authenticated: boolean;
  teacher: typeof fx.teacher;
  sources: SourceOut[];
  sheets: Record<string, SheetOut>;
  scans: Record<string, ScanOut>;
  jobs: Record<string, JobOut & { ticks: number }>;
  approvals: Set<string>;
}

const state: MockState = {
  // The fixture teacher is already signed in: a screenshot test should land on
  // the screen it is testing, not on the login form.
  authenticated: true,
  teacher: structuredClone(fx.teacher),
  sources: structuredClone(fx.sources),
  sheets: { [fx.sheet.id]: structuredClone(fx.sheet) },
  scans: { [fx.scan.id]: structuredClone(fx.scan) },
  jobs: {},
  approvals: new Set<string>(),
};

let jobCounter = 0;

function startJob(kind: JobOut['kind'], result: Record<string, unknown>): JobOut {
  jobCounter += 1;
  const job: JobOut & { ticks: number } = {
    id: fx.id(900 + jobCounter),
    kind,
    status: 'queued',
    progress: 0,
    message: null,
    result: null,
    error: null,
    created_at: fx.NOW,
    finished_at: null,
    ticks: 0,
  };
  state.jobs[job.id] = job;
  // The finished result is stashed until the job reports success.
  pendingResults[job.id] = result;
  return stripTicks(job);
}

const pendingResults: Record<string, Record<string, unknown>> = {};

function stripTicks(job: JobOut & { ticks: number }): JobOut {
  const { ticks: _ticks, ...rest } = job;
  return rest;
}

/** Each poll advances the job, so the progress bar in the UI actually moves. */
function pollJob(jobId: string): JobOut {
  const job = state.jobs[jobId];
  if (!job) throw new ApiError(404, 'not_found', 'job not found');
  job.ticks += 1;
  if (job.ticks >= 4) {
    job.status = 'succeeded';
    job.progress = 1;
    job.result = pendingResults[jobId] ?? {};
    job.finished_at = fx.NOW;
  } else {
    job.status = 'running';
    job.progress = Math.round((job.ticks / 4) * 100) / 100;
  }
  return stripTicks(job);
}

function match(path: string, pattern: RegExp): RegExpMatchArray | null {
  return path.match(pattern);
}

function requireAuth(): void {
  if (!state.authenticated) throw new ApiError(401, 'unauthorized', 'authentication required');
}

/** Resets everything between tests. Exposed on `window` in mock builds only. */
export function resetMockState(): void {
  state.authenticated = true;
  state.teacher = structuredClone(fx.teacher);
  state.sources = structuredClone(fx.sources);
  state.sheets = { [fx.sheet.id]: structuredClone(fx.sheet) };
  state.scans = { [fx.scan.id]: structuredClone(fx.scan) };
  state.jobs = {};
  state.approvals = new Set<string>();
  jobCounter = 0;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Json = any;

export async function handleMock<T>(method: string, url: string, body: unknown): Promise<T> {
  const [rawPath] = url.split('?');
  const path = rawPath ?? '';
  const result = route(method, path, body);
  return result as T;
}

function route(method: string, path: string, body: unknown): Json {
  /* ---------------------------------------------------------- auth --- */
  if (method === 'POST' && path === '/auth/login') {
    state.authenticated = true;
    return state.teacher;
  }
  if (method === 'POST' && path === '/auth/logout') {
    state.authenticated = false;
    return undefined;
  }
  if (method === 'GET' && path === '/auth/me') {
    requireAuth();
    return state.teacher;
  }
  if (method === 'PATCH' && path === '/teachers/me/preferences') {
    requireAuth();
    state.teacher = {
      ...state.teacher,
      preferences: { ...state.teacher.preferences, ...(body as Partial<TeacherPreferences>) },
    };
    return state.teacher;
  }

  requireAuth();

  /* ---------------------------------------------------------- home --- */
  if (method === 'GET' && path === '/home') return { ...fx.home, teacher: state.teacher };
  if (method === 'GET' && path === '/classes') return fx.classes;
  if (method === 'GET' && path === '/subjects') return fx.subjects;
  if (method === 'GET' && path === '/chapters') return fx.chapters;

  let m = match(path, /^\/classes\/([^/]+)\/students$/);
  if (m) return method === 'POST' ? fx.students : fx.students;

  m = match(path, /^\/classes\/([^/]+)\/mastery$/);
  if (m && method === 'GET') {
    return m[1] === fx.classes[1]?.id
      ? { ...fx.masteryMatrix, class_id: m[1], cells: [] }
      : fx.masteryMatrix;
  }

  m = match(path, /^\/classes\/([^/]+)$/);
  if (m && method === 'GET') {
    const found = fx.classes.find((c) => c.id === m?.[1]);
    if (!found) throw new ApiError(404, 'not_found', 'class not found');
    return found;
  }

  m = match(path, /^\/curricula\/([^/]+)\/competencies$/);
  if (m && method === 'GET') return fx.competencies;

  m = match(path, /^\/students\/([^/]+)\/mastery$/);
  if (m && method === 'GET') return fx.studentProfile(m[1] ?? '');

  /* ------------------------------------------------------- sources --- */
  if (method === 'GET' && path === '/sources') return state.sources;
  if (method === 'POST' && path === '/sources') {
    // The fixture layer has to reject what the API rejects. It used to accept
    // an upload with no subject_id, which is exactly the 422 the real client
    // was sending on every upload — invisible to the whole e2e suite.
    if (!(body instanceof FormData) || !body.get('subject_id')) {
      throw new ApiError(422, 'validation_error', 'request body failed validation', {
        errors: [{ loc: ['body', 'subject_id'], msg: 'Field required', type: 'missing' }],
      });
    }
    const created: SourceOut = {
      ...(fx.sources[1] as SourceOut),
      id: fx.id(410 + state.sources.length),
      filename: 'nouveau-manuel.pdf',
      status: 'queued',
      exercise_count: 0,
    };
    state.sources = [created, ...state.sources];
    return startJob('ingest_source', { source_id: created.id });
  }
  m = match(path, /^\/sources\/([^/]+)\/exercises$/);
  if (m && method === 'GET') return fx.exercises;
  m = match(path, /^\/sources\/([^/]+)(?:\/status)?$/);
  if (m && method === 'GET') {
    const found = state.sources.find((s) => s.id === m?.[1]);
    if (!found) throw new ApiError(404, 'not_found', 'source not found');
    return found;
  }

  /* ----------------------------------------------------- exercises --- */
  m = match(path, /^\/exercises\/([^/]+)$/);
  if (m && method === 'PATCH') {
    const update = body as ExerciseUpdate;
    if (update.approved) state.approvals.add(m[1] ?? '');
    const base =
      fx.exercises.find((e) => e.id === m?.[1]) ??
      fx.adaptive.plans.flatMap((p) => p.generated).map((p) => p.exercise).find((e) => e.id === m?.[1]);
    if (!base) throw new ApiError(404, 'not_found', 'exercise not found');
    return { ...base, ...update, approved_at: update.approved ? fx.NOW : base.approved_at };
  }

  /* -------------------------------------------------------- sheets --- */
  if (method === 'POST' && path === '/sheets/propose') {
    return { proposals: fx.proposals, language: 'fr' };
  }
  if (method === 'POST' && path === '/sheets') {
    const payload = body as SheetCreate;
    const created: SheetOut = {
      ...structuredClone(fx.sheet),
      id: fx.id(601),
      title: payload.title,
      intent: payload.intent ?? null,
      class_id: payload.class_id,
      subject_id: payload.subject_id,
      language: payload.language,
    };
    state.sheets[created.id] = created;
    return created;
  }
  m = match(path, /^\/sheets\/([^/]+)\/render$/);
  if (m && method === 'POST') {
    const sheetId = m[1] ?? '';
    return startJob('render_sheet', {
      blank_pdf_url: `/mock/${sheetId}-blank.pdf`,
      answer_key_pdf_url: `/mock/${sheetId}-answer-key.pdf`,
    });
  }
  m = match(path, /^\/sheets\/([^/]+)$/);
  if (m) {
    const sheetId = m[1] ?? '';
    const found = state.sheets[sheetId] ?? state.sheets[fx.sheet.id];
    if (!found) throw new ApiError(404, 'not_found', 'sheet not found');
    if (method === 'PATCH') return found;
    return { ...found, id: sheetId };
  }

  /* --------------------------------------------------------- scans --- */
  if (method === 'POST' && path === '/scans') {
    return startJob('process_scan', { scan_id: fx.scan.id });
  }
  m = match(path, /^\/scans\/([^/]+)\/detections\/([^/]+)$/);
  if (m && method === 'PATCH') {
    const [, scanId, detectionId] = m;
    const target = state.scans[scanId ?? ''] ?? state.scans[fx.scan.id];
    if (!target) throw new ApiError(404, 'not_found', 'scan not found');
    for (const page of target.pages) {
      for (const detection of page.detections) {
        if (detection.id !== detectionId) continue;
        detection.detected_index = (body as DetectionCorrection).detected_index;
        detection.outcome = 'corrected';
        detection.corrected_at = fx.NOW;
        detection.confidence = 1;
        return detection;
      }
    }
    throw new ApiError(404, 'not_found', 'detection not found');
  }
  m = match(path, /^\/scans\/([^/]+)\/detections$/);
  if (m && method === 'GET') {
    const target = state.scans[m[1] ?? ''] ?? state.scans[fx.scan.id];
    return target ? target.pages.flatMap((p) => p.detections) : [];
  }
  m = match(path, /^\/scans\/([^/]+)\/pages\/([^/]+)\/assign$/);
  if (m && method === 'POST') {
    const target = state.scans[m[1] ?? ''] ?? state.scans[fx.scan.id];
    const page = target?.pages.find((p) => p.id === m?.[2]);
    if (!page) throw new ApiError(404, 'not_found', 'page not found');
    page.student_id = (body as { student_id: string }).student_id;
    page.detected_uid =
      fx.students.find((s) => s.id === page.student_id)?.uid ?? page.detected_uid;
    return page;
  }
  m = match(path, /^\/scans\/([^/]+)\/confirm$/);
  if (m && method === 'POST') {
    const target = state.scans[m[1] ?? ''] ?? state.scans[fx.scan.id];
    if (target) target.status = 'confirmed';
    return { attempts_created: 12, students_affected: 2, competencies_updated: 5 };
  }
  m = match(path, /^\/scans\/([^/]+)$/);
  if (m && method === 'GET') {
    const target = state.scans[m[1] ?? ''] ?? state.scans[fx.scan.id];
    if (!target) throw new ApiError(404, 'not_found', 'scan not found');
    return { ...target, id: m[1] ?? target.id };
  }

  /* ------------------------------------------------------ adaptive --- */
  if (method === 'POST' && path === '/adaptive/propose') {
    return {
      ...fx.adaptive,
      plans: fx.adaptive.plans.map((plan) => ({
        ...plan,
        generated: plan.generated.map((proposal) => ({
          ...proposal,
          exercise: {
            ...proposal.exercise,
            approved_at: state.approvals.has(proposal.exercise.id) ? fx.NOW : null,
          },
        })),
      })),
    };
  }
  if (method === 'POST' && path === '/adaptive/batch') {
    const payload = body as AdaptiveBatchRequest;
    return startJob('generate_adaptive', {
      pdf_url: '/mock/adaptive-batch.pdf',
      student_count: payload.plans.length,
    });
  }

  /* ---------------------------------------------------------- jobs --- */
  m = match(path, /^\/jobs\/([^/]+)$/);
  if (m && method === 'GET') return pollJob(m[1] ?? '');

  throw new ApiError(404, 'not_found', `no fixture for ${method} ${path}`);
}
