/**
 * The fixture layer. Every screen renders — and every screenshot test runs —
 * without a backend. It answers the same shapes as `alppy/schemas` and raises
 * the same `ApiError` envelope, so nothing downstream knows the difference.
 */
import { ApiError } from '../client';
import type {
  AdaptiveApproveRequest,
  AdaptiveBatchRequest,
  AdaptiveDiscardRequest,
  AdaptiveRegenerateRequest,
  DetectionCorrection,
  ExerciseCreate,
  ExerciseOut,
  ExerciseUpdate,
  JobOut,
  ScanOut,
  SheetCreate,
  SheetDraftPreview,
  SheetOut,
  SourceOut,
  SourceSectionOut,
  TeacherPreferences,
} from '../types';
import * as fx from './fixtures';

interface MockState {
  authenticated: boolean;
  teacher: typeof fx.teacher;
  sources: SourceOut[];
  sections: SourceSectionOut[];
  /** Exercises live in state, not in the fixture module, because the builder
   *  can add one and must then see it in the list. */
  exercises: ExerciseOut[];
  /** Sections whose extraction job is running. Flipped to extracted when the
   *  job completes, so the builder's "reading the chapter" state is reachable. */
  pendingExtractions: Set<string>;
  sheets: Record<string, SheetOut>;
  scans: Record<string, ScanOut>;
  jobs: Record<string, JobOut & { ticks: number }>;
  approvals: Set<string>;
  discards: Set<string>;
}

const state: MockState = {
  // The fixture teacher is already signed in: a screenshot test should land on
  // the screen it is testing, not on the login form.
  authenticated: true,
  teacher: structuredClone(fx.teacher),
  sources: structuredClone(fx.sources),
  sections: structuredClone(fx.sourceSections),
  exercises: structuredClone(fx.exercises),
  pendingExtractions: new Set<string>(),
  sheets: { [fx.sheet.id]: structuredClone(fx.sheet) },
  scans: { [fx.scan.id]: structuredClone(fx.scan) },
  jobs: {},
  approvals: new Set<string>(),
  discards: new Set<string>(),
};

let jobCounter = 0;
let regenerateCounter = 0;

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

/** Flip a section to extracted and give it exercises to show. */
function completeExtraction(sectionId: string): void {
  if (!sectionId || !state.pendingExtractions.has(sectionId)) return;
  state.pendingExtractions.delete(sectionId);
  const section = state.sections.find((sec) => sec.id === sectionId);
  if (!section) return;
  const made = fx.exercisesForSection(section, state.exercises.length);
  state.exercises = [...state.exercises, ...made];
  section.extracted_at = fx.NOW;
}

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
    // A finished extraction is what turns a chapter from "never read" into one
    // the picker can list, so the fixture has to make that transition happen —
    // otherwise the builder's on-demand path has no reachable end state.
    if (job.kind === 'extract_section') {
      const sectionId = String(pendingResults[jobId]?.section_id ?? '');
      completeExtraction(sectionId);
    }
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
  state.sections = structuredClone(fx.sourceSections);
  state.exercises = structuredClone(fx.exercises);
  state.pendingExtractions = new Set<string>();
  state.sheets = { [fx.sheet.id]: structuredClone(fx.sheet) };
  state.scans = { [fx.scan.id]: structuredClone(fx.scan) };
  state.jobs = {};
  state.approvals = new Set<string>();
  state.discards = new Set<string>();
  globalThis.__alppyMockCalls = [];
  jobCounter = 0;
  regenerateCounter = 0;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Json = any;

/**
 * Every call this mock served, newest last, as `"POST /adaptive/approve"`.
 *
 * The mock answers in-process, so a Playwright test cannot watch the network to
 * find out whether a button actually called the API — which is exactly how a
 * button that only set React state passed for working. This is the seam that
 * lets a test tell the difference. Test-only: nothing in the app reads it.
 */
declare global {
  // eslint-disable-next-line no-var
  var __alppyMockCalls: string[] | undefined;
}

function record(method: string, url: string): void {
  if (typeof globalThis === 'undefined') return;
  globalThis.__alppyMockCalls ??= [];
  // The full URL, query string included. Recording only the path made a
  // filtered request indistinguishable from an unfiltered one in the log — the
  // exact confusion this seam exists to remove, one layer further in. Paths
  // with no query are unchanged, so assertions anchored on them still hold.
  globalThis.__alppyMockCalls.push(`${method} ${url}`);
}

export async function handleMock<T>(method: string, url: string, body: unknown): Promise<T> {
  const [rawPath, rawQuery] = url.split('?');
  const path = rawPath ?? '';
  record(method, url);
  // The query string used to be dropped on the floor, so a filtered or sorted
  // request was indistinguishable from an unfiltered one and no e2e test could
  // tell whether the controls did anything.
  const query = new URLSearchParams(rawQuery ?? '');
  const result = route(method, path, body, query);
  return result as T;
}

function route(method: string, path: string, body: unknown, query: URLSearchParams): Json {
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
  if (method === 'GET' && path === '/timeline') return fx.timeline;

  let m = match(path, /^\/classes\/([^/]+)\/students$/);
  if (m) return method === 'POST' ? fx.students : fx.students;

  m = match(path, /^\/classes\/([^/]+)\/mastery$/);
  if (m && method === 'GET') {
    if (m[1] === fx.classes[1]?.id) {
      return { ...fx.masteryMatrix, class_id: m[1], cells: [], competencies: [] };
    }
    return fx.classMastery(m[1] ?? '', query);
  }

  m = match(path, /^\/classes\/([^/]+)$/);
  if (m && method === 'GET') {
    const found = fx.classes.find((c) => c.id === m?.[1]);
    if (!found) throw new ApiError(404, 'not_found', 'class not found');
    return found;
  }

  m = match(path, /^\/curricula\/([^/]+)\/competencies$/);
  if (m && method === 'GET') return fx.competencies;

  m = match(path, /^\/students\/([^/]+)\/competencies\/([^/]+)\/attempts$/);
  if (m && method === 'GET') return fx.competencyAttempts(m[1] ?? '', m[2] ?? '');

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
  m = match(path, /^\/sources\/([^/]+)\/sections$/);
  if (m && method === 'GET') {
    const sourceId = m[1] ?? '';
    if (sourceId !== fx.sources[0]?.id) return [];
    // Counted from the rows rather than stored on the fixture: a hardcoded
    // count that disagreed with the list underneath it read as a broken filter.
    return state.sections.map((section) => ({
      ...section,
      exercise_count: state.exercises.filter((e) => e.source_section_id === section.id).length,
    }));
  }
  m = match(path, /^\/sources\/([^/]+)\/sections\/([^/]+)\/extract$/);
  if (m && method === 'POST') {
    const sectionId = m[2] ?? '';
    const section = state.sections.find((sec) => sec.id === sectionId);
    if (!section) throw new ApiError(404, 'not_found', 'source section not found');
    // The job the real API returns. The rows only appear once it succeeds, so
    // the fixture flips the section when the job is polled to completion.
    state.pendingExtractions.add(sectionId);
    return startJob('extract_section', { section_id: sectionId });
  }
  m = match(path, /^\/sources\/([^/]+)\/exercises$/);
  if (m && method === 'GET') {
    // Filter and page exactly as Postgres does, or the builder's counters and
    // its "1–20 of 186" line would be testing something the API never returns.
    const sectionId = query.get('section_id');
    const chapterId = query.get('chapter_id');
    const kind = query.get('type');
    const difficulty = query.get('difficulty');
    const q = (query.get('q') ?? '').trim().toLowerCase();
    const offset = Number(query.get('offset') ?? 0);
    const limit = Number(query.get('limit') ?? 20);

    const matched = state.exercises
      .filter((e) => {
        if (sectionId && e.source_section_id !== sectionId) return false;
        if (chapterId && e.chapter_id !== chapterId) return false;
        if (difficulty && e.difficulty !== Number(difficulty)) return false;
        if (q && !e.statement.toLowerCase().includes(q)) return false;
        return true;
      })
      // The API orders by the book's own page (`ORDER BY source_page`). Serving
      // insertion order here made the picker's page-group headers read 84, 85,
      // 86, 78, 79 — a bug in the fixture that looks exactly like a bug in the
      // grouping.
      .sort((a, b) => (a.source_page ?? 0) - (b.source_page ?? 0));
    // Facets ignore the type filter on purpose: a chip reports what selecting
    // it would give, not what it gives once selected.
    const facets = {
      total: matched.length,
      mcq: matched.filter((e) => e.type === 'mcq').length,
      true_false: matched.filter((e) => e.type === 'true_false').length,
      open: matched.filter((e) => e.type === 'open').length,
    };
    const filtered = kind ? matched.filter((e) => e.type === kind) : matched;
    return {
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
      offset,
      limit,
      facets,
    };
  }
  m = match(path, /^\/sources\/([^/]+)(?:\/status)?$/);
  if (m && method === 'GET') {
    const found = state.sources.find((s) => s.id === m?.[1]);
    if (!found) throw new ApiError(404, 'not_found', 'source not found');
    return found;
  }

  /* ----------------------------------------------------- exercises --- */
  if (method === 'POST' && path === '/exercises') {
    const payload = body as ExerciseCreate;
    const created: ExerciseOut = {
      id: fx.id(700 + state.exercises.length),
      type: payload.type,
      // Written by a teacher: neither a transcription nor a model's proposal,
      // so no source page, no accent, and approved by construction.
      origin: 'teacher',
      language: payload.language,
      statement: payload.statement,
      options: payload.options ?? null,
      answer_index: payload.answer_index ?? null,
      answer_bool: payload.answer_bool ?? null,
      answer_text: payload.answer_text ?? null,
      explanation: payload.explanation ?? null,
      difficulty: payload.difficulty ?? 3,
      chapter_id: payload.chapter_id ?? null,
      competency_ids: payload.competency_ids ?? [],
      source_id: null,
      source_section_id: null,
      source_page: null,
      approved_at: fx.NOW,
    };
    state.exercises = [...state.exercises, created];
    return created;
  }
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
  if (method === 'POST' && path === '/sheets/preview') {
    const draft = body as SheetDraftPreview;
    if (!draft.items?.length) {
      throw new ApiError(422, 'unprocessable', 'a sheet with no items cannot be previewed');
    }
    return fx.draftPreviewHtml(draft);
  }
  if (method === 'GET' && path === '/sheets') {
    // The list is scoped to a class now, so the fixture layer has to honour
    // `class_id` or the screen would look unscoped in the screenshot suite.
    const classId = query.get('class_id');
    const all = Object.values(state.sheets);
    return classId ? all.filter((sheet) => sheet.class_id === classId) : all;
  }
  if (method === 'GET' && path === '/scans') {
    const sheetId = query.get('sheet_id');
    const all = Object.values(state.scans);
    return sheetId ? all.filter((scan) => scan.sheet_id === sheetId) : all;
  }
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
  m = match(path, /^\/sheets\/([^/]+)\/printed$/);
  if (m && method === 'POST') {
    const sheetId = m[1] ?? '';
    // Bookkeeping only: it records the print, it changes nothing about the
    // sheet, so the mock returns the sheet unchanged.
    return state.sheets[sheetId] ?? fx.sheet;
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
        // A discarded item is never proposed again.
        generated: plan.generated
          .filter((proposal) => !state.discards.has(proposal.exercise.id))
          .map((proposal) => ({
            ...proposal,
            exercise: {
              ...proposal.exercise,
              approved_at: state.approvals.has(proposal.exercise.id) ? fx.NOW : null,
            },
          })),
      })),
    };
  }
  if (method === 'POST' && path === '/adaptive/approve') {
    const ids = (body as AdaptiveApproveRequest).exercise_ids;
    ids.forEach((id) => state.approvals.add(id));
    return { approved: ids.length, exercise_ids: ids };
  }
  if (method === 'POST' && path === '/adaptive/discard') {
    const ids = (body as AdaptiveDiscardRequest).exercise_ids;
    ids.forEach((id) => {
      state.approvals.delete(id);
      state.discards.add(id);
    });
    return { discarded: ids.length, exercise_ids: ids };
  }
  if (method === 'POST' && path === '/adaptive/regenerate') {
    const { exercise_id: replaced } = body as AdaptiveRegenerateRequest;
    state.discards.add(replaced);
    state.approvals.delete(replaced);
    // A replacement, not an addition: a fresh id, unapproved like any other
    // generated item, so the approval step has to happen again.
    regenerateCounter += 1;
    const source = fx.adaptive.plans
      .flatMap((plan) => plan.generated)
      .find((proposal) => proposal.exercise.id === replaced);
    const base = source ?? fx.adaptive.plans[0]?.generated[0];
    if (!base) throw new ApiError(404, 'not_found', 'exercise not found');
    return {
      replaced_exercise_id: replaced,
      proposal: {
        ...base,
        exercise: {
          ...base.exercise,
          id: fx.id(700 + regenerateCounter),
          statement: `${base.exercise.statement} (v${regenerateCounter + 1})`,
          approved_at: null,
        },
      },
    };
  }
  // Creating the batch returns the SHEET. Rendering it is a second call that
  // returns the job — the mock mirrors the real contract, because a mock that
  // agrees with a wrong client hides the bug instead of catching it.
  if (method === 'POST' && path === '/adaptive/batch') {
    const payload = body as AdaptiveBatchRequest;
    const created: SheetOut = {
      ...structuredClone(fx.sheet),
      id: fx.id(602),
      title: payload.title,
      target: 'student',
      class_id: payload.class_id,
      subject_id: payload.subject_id,
      language: payload.language,
      blank_pdf_url: null,
      answer_key_pdf_url: null,
      feedback_pdf_url: null,
      derived_from_id: payload.source_sheet_id ?? null,
      rendered_at: null,
      instances: payload.plans.map((plan, index) => ({
        id: fx.id(650 + index),
        student_id: plan.student_id,
        student_uid: plan.student_uid,
        page_count: 1,
        group_label: plan.group_label ?? null,
        has_feedback: plan.feedback_id != null,
      })),
    };
    state.sheets[created.id] = created;
    return created;
  }
  m = match(path, /^\/adaptive\/batch\/([^/]+)\/render$/);
  if (m && method === 'POST') {
    const sheetId = m[1] ?? '';
    const target = state.sheets[sheetId];
    if (!target) throw new ApiError(404, 'not_found', 'sheet not found');
    // The worker writes both keys onto the sheet; the download links come from
    // re-reading it. Always two documents (DESIGN.md §9).
    target.blank_pdf_url = `/mock/${sheetId}-adaptive-batch.pdf`;
    target.answer_key_pdf_url = `/mock/${sheetId}-adaptive-batch-answer-key.pdf`;
    target.rendered_at = fx.NOW;
    return startJob('generate_adaptive', {
      batch_pdf_key: `sheets/${sheetId}/v1/adaptive-batch.pdf`,
      answer_key_pdf_key: `sheets/${sheetId}/v1/adaptive-batch-answer-key.pdf`,
    });
  }

  /* ---------------------------------------------------------- jobs --- */
  m = match(path, /^\/jobs\/([^/]+)$/);
  if (m && method === 'GET') return pollJob(m[1] ?? '');

  throw new ApiError(404, 'not_found', `no fixture for ${method} ${path}`);
}
