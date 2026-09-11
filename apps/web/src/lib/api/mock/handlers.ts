/**
 * The fixture layer. Every screen renders — and every screenshot test runs —
 * without a backend. It answers the same shapes as `alppy/schemas` and raises
 * the same `ApiError` envelope, so nothing downstream knows the difference.
 */
import { ApiError } from '../client';
import type {
  AdaptiveProposeResponse,
  AdaptiveApproveRequest,
  AdaptiveBatchRequest,
  AdaptiveDiscardRequest,
  AdaptiveRegenerateRequest,
  ClassOut,
  ClassTeacherOut,
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
  /** Classes live in state because the teaching screen writes to them: who
   *  teaches what, and what the class studies, both change under the pointer. */
  classes: ClassOut[];
  classTeachers: Record<string, ClassTeacherOut[]>;
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
  sheets: {
    [fx.sheet.id]: structuredClone(fx.sheet),
    [fx.renderedSheet.id]: structuredClone(fx.renderedSheet),
  },
  scans: { [fx.scan.id]: structuredClone(fx.scan) },
  jobs: {},
  approvals: new Set<string>(),
  discards: new Set<string>(),
  classes: structuredClone(fx.classes),
  classTeachers: structuredClone(fx.classTeachers),
};

let jobCounter = 0;
let regenerateCounter = 0;

/**
 * Which kind each job was, kept where a reload cannot lose it.
 *
 * The fixture's state is module state: it dies with the page. The real API's
 * jobs are rows, and the whole of F4 rests on that difference — a proposal
 * outlives the tab that asked for it, which is why putting the job id in the
 * URL is worth doing at all. A fixture that forgets every job on reload cannot
 * model the one property the feature depends on, and a test written against it
 * would be testing the fixture's amnesia.
 *
 * So the kind is remembered — in `localStorage`, not `sessionStorage`, because
 * a server is shared between a teacher's tabs and `sessionStorage` is not.
 * That is all that is needed: the proposal itself is rebuilt from the fixtures
 * on demand (`currentProposal`), exactly as the server rebuilds it from its
 * stored payload.
 */
const JOB_KINDS_KEY = 'alppy.mock.jobKinds';

function rememberJobKind(id: string, kind: JobOut['kind']): void {
  try {
    const raw = JSON.parse(window.localStorage.getItem(JOB_KINDS_KEY) ?? '{}') as Record<
      string,
      string
    >;
    raw[id] = kind;
    window.localStorage.setItem(JOB_KINDS_KEY, JSON.stringify(raw));
  } catch {
    /* No storage: the fixture simply forgets, as it always did. */
  }
}

function rememberedJobKind(id: string): JobOut['kind'] | null {
  try {
    const raw = JSON.parse(window.localStorage.getItem(JOB_KINDS_KEY) ?? '{}') as Record<
      string,
      JobOut['kind']
    >;
    return raw[id] ?? null;
  } catch {
    return null;
  }
}

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
  rememberJobKind(job.id, kind);
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

/** The proposal as it currently stands, with approvals and discards applied. */
function currentProposal(): AdaptiveProposeResponse {
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

function stripTicks(job: JobOut & { ticks: number }): JobOut {
  const { ticks: _ticks, ...rest } = job;
  return rest;
}

/** Each poll advances the job, so the progress bar in the UI actually moves. */
function pollJob(jobId: string): JobOut {
  let job = state.jobs[jobId];
  if (!job) {
    // A job this page never started: the reload case. The server would answer
    // with the finished row, so the fixture does too, rather than the 404 that
    // made a recovered run look like a lost one.
    const kind = rememberedJobKind(jobId);
    if (!kind) throw new ApiError(404, 'not_found', 'job not found');
    job = {
      id: jobId,
      kind,
      status: 'succeeded',
      progress: 1,
      message: null,
      result: {},
      error: null,
      created_at: fx.NOW,
      finished_at: fx.NOW,
      ticks: 4,
    };
    state.jobs[jobId] = job;
  }
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

/* ------------------------------------------- who teaches what (D75) --- */

function requireClass(classId: string): ClassOut {
  const found = state.classes.find((c) => c.id === classId);
  if (!found) throw new ApiError(404, 'not_found', 'class not found');
  return found;
}

/**
 * `subject_ids` is what THIS CALLER teaches, so it only moves when the row
 * being written is the signed-in teacher's. Writing it for a colleague is how
 * a mock would quietly tell the tree it had gained a branch it cannot open.
 */
function syncOwnBranches(klass: ClassOut): void {
  const mine = (state.classTeachers[klass.id] ?? []).find(
    (row) => row.teacher_id === state.teacher.id,
  );
  const declared = klass.declared_subject_ids ?? [];
  klass.subject_ids = declared.filter((id) => (mine?.subject_ids ?? []).includes(id));
}

function assign(klass: ClassOut, teacherId: string, subjectId: string): void {
  const rows = (state.classTeachers[klass.id] ??= []);
  let row = rows.find((r) => r.teacher_id === teacherId);
  if (!row) {
    const who = fx.colleagues.find((c) => c.id === teacherId);
    if (!who) throw new ApiError(422, 'unprocessable', 'no such colleague in this school');
    row = {
      teacher_id: teacherId,
      first_name: who.first_name,
      last_name: who.last_name,
      subject_ids: [],
      is_head: klass.head_teacher_id === teacherId,
    };
    rows.push(row);
  }
  // Idempotent, like the endpoint: assigning twice is not an error.
  if (!row.subject_ids.includes(subjectId)) row.subject_ids = [...row.subject_ids, subjectId];
  syncOwnBranches(klass);
}

function unassign(klass: ClassOut, teacherId: string, subjectId: string): void {
  const rows = state.classTeachers[klass.id] ?? [];
  const row = rows.find((r) => r.teacher_id === teacherId);
  if (!row) return;
  row.subject_ids = row.subject_ids.filter((id) => id !== subjectId);
  // A head teacher keeps their footing with no branches at all — that is the
  // union arm of `owned_class_ids`, and dropping the row here would make the
  // fixture claim a class can become unowned.
  if (row.subject_ids.length === 0 && !row.is_head) {
    state.classTeachers[klass.id] = rows.filter((r) => r.teacher_id !== teacherId);
  }
  syncOwnBranches(klass);
}

/**
 * How many sheets a branch holds IN ONE CLASS, counted the way the API counts
 * them — and the way the refusal sentence already claimed it did.
 *
 * It used to count every sheet in the school with that `subject_id` and report
 * the total as sheets "in this class", which happened to agree while the fixtures
 * held exactly one sheet. Adding a second (`renderedSheet`) made the two
 * disagree: removing maths from 7B reported two sheets, one of which was not in
 * 7B at all.
 */
function sheetsHeld(classId: string, subjectId: string): number {
  return Object.values(state.sheets).filter(
    (s) => s.subject_id === subjectId && s.class_id === classId,
  ).length;
}

/** Resets everything between tests. Exposed on `window` in mock builds only. */
export function resetMockState(): void {
  state.authenticated = true;
  state.teacher = structuredClone(fx.teacher);
  state.sources = structuredClone(fx.sources);
  state.sections = structuredClone(fx.sourceSections);
  state.exercises = structuredClone(fx.exercises);
  state.pendingExtractions = new Set<string>();
  state.sheets = {
    [fx.sheet.id]: structuredClone(fx.sheet),
    [fx.renderedSheet.id]: structuredClone(fx.renderedSheet),
  };
  state.scans = { [fx.scan.id]: structuredClone(fx.scan) };
  state.jobs = {};
  state.approvals = new Set<string>();
  state.discards = new Set<string>();
  state.classes = structuredClone(fx.classes);
  state.classTeachers = structuredClone(fx.classTeachers);
  globalThis.__alppyMockCalls = [];
  globalThis.__alppyMockFail = [];
  globalThis.__alppyMockKeys = [];
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
  var __alppyMockCalls: string[] | undefined;

  var __alppyMockFail: MockFailure[] | undefined;

  var __alppyMockKeys: { call: string; key: string }[] | undefined;
}

/**
 * A failure a test asks the mock to produce, so an error path can be exercised
 * on the real screen.
 *
 * Playwright's `page.route` cannot help here: in mock mode `apiRequest` never
 * reaches `fetch` at all, it calls `handleMock` in-process. So a test that wants
 * to know what a teacher sees when a correction comes back 500 has nowhere to
 * inject the 500 — which is exactly how a mutation with no error reader passed
 * for working. Same seam, same rule as `__alppyMockCalls`: test-only, nothing in
 * the app reads it, and an empty list changes nothing.
 *
 * `method` and `pattern` are matched against the request; `pattern` is a
 * substring of the URL, not a regex, because a test naming one route should not
 * have to escape it. `times` spends itself, so a test can fail the first attempt
 * and let the retry through.
 */
export interface MockFailure {
  method: string;
  pattern: string;
  status: number;
  code: string;
  /** How many matching calls to fail. Absent fails every one. */
  times?: number;
}

let failureCounter = 0;

function failureFor(method: string, url: string): MockFailure | undefined {
  const queued = globalThis.__alppyMockFail;
  if (!queued || queued.length === 0) return undefined;
  const hit = queued.find((f) => f.method === method && url.includes(f.pattern));
  if (!hit) return undefined;
  if (hit.times !== undefined) {
    hit.times -= 1;
    if (hit.times <= 0) queued.splice(queued.indexOf(hit), 1);
  }
  return hit;
}

function record(method: string, url: string, headers?: Record<string, string>): void {
  if (typeof globalThis === 'undefined') return;
  // The idempotency key, kept separately: a test asserting that a retry reuses one
  // key and a fresh intent mints another has to see the HEADER, and the call log
  // is deliberately a flat list of readable strings. Test-only, same as the log.
  const key = headers?.['Idempotency-Key'];
  if (key !== undefined) {
    globalThis.__alppyMockKeys ??= [];
    globalThis.__alppyMockKeys.push({ call: `${method} ${url}`, key });
  }
  globalThis.__alppyMockCalls ??= [];
  // The full URL, query string included. Recording only the path made a
  // filtered request indistinguishable from an unfiltered one in the log — the
  // exact confusion this seam exists to remove, one layer further in. Paths
  // with no query are unchanged, so assertions anchored on them still hold.
  globalThis.__alppyMockCalls.push(`${method} ${url}`);
}

export async function handleMock<T>(
  method: string,
  url: string,
  body: unknown,
  headers?: Record<string, string>,
): Promise<T> {
  const [rawPath, rawQuery] = url.split('?');
  const path = rawPath ?? '';
  record(method, url, headers);
  // Before anything is mutated: a test asking for a 500 wants the state the
  // teacher's screen was in, not that state with the write half-applied.
  const failure = failureFor(method, url);
  if (failure) {
    // With a request id, because the real envelope always carries one
    // (`api/errors.py`) and a screen that renders it has to have something to
    // render. Stable per failure so a test can read it back.
    throw new ApiError(
      failure.status,
      failure.code,
      `injected ${failure.status}`,
      {},
      `mock-${failure.status}-${(failureCounter += 1)}`,
    );
  }
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
  if (method === 'PATCH' && path === '/schools/me') {
    requireAuth();
    const patch = body as { name?: string; canton?: string };
    state.teacher = {
      ...state.teacher,
      schools: (state.teacher.schools ?? []).map((s) =>
        s.id === state.teacher.school_id ? { ...s, ...patch } : s,
      ),
    };
    return (state.teacher.schools ?? []).find((s) => s.id === state.teacher.school_id);
  }
  if (method === 'POST' && path === '/subjects') {
    requireAuth();
    const created = { id: crypto.randomUUID(), ...(body as { key: string; labels: object }) };
    fx.subjects.push(created as never);
    return created;
  }
  if (method === 'PATCH' && path.startsWith('/subjects/')) {
    requireAuth();
    const id = path.slice('/subjects/'.length);
    const subject = fx.subjects.find((s) => s.id === id);
    if (!subject) throw new ApiError(404, 'not_found', 'subject not found');
    Object.assign(subject, body);
    return subject;
  }
  if (method === 'POST' && path.startsWith('/auth/school/')) {
    requireAuth();
    const schoolId = path.slice('/auth/school/'.length);
    const target = (state.teacher.schools ?? []).find((s) => s.id === schoolId);
    // A school the teacher does not work at is MISSING, not forbidden — the
    // mock has to answer the way the API does or the client's error path is
    // never exercised.
    if (!target) throw new ApiError(404, 'not_found', 'school not found');
    state.teacher = { ...state.teacher, school_id: target.id };
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
  if (method === 'GET' && path === '/classes') {
    // Honoured, not ignored. The client now sends `school_year_id` on this route
    // and on `/home`, `/sheets` and `/scans`, and a fixture layer that dropped it
    // would make a wired-up year indistinguishable from an unwired one — the
    // exact confusion G3 is about.
    const yearId = query.get('school_year_id');
    return yearId
      ? state.classes.filter((klass) => klass.school_year_id === yearId)
      : state.classes;
  }
  if (method === 'GET' && path === '/school-years') return fx.schoolYears;
  if (method === 'GET' && path === '/subjects') return fx.subjects;
  if (method === 'GET' && path === '/chapters') return fx.chapters;
  if (method === 'GET' && path === '/timeline') return fx.timeline;

  let m = match(path, /^\/classes\/([^/]+)\/students$/);
  if (m) return method === 'POST' ? fx.students : fx.students;

  m = match(path, /^\/sheets\/([^/]+)\/mastery$/);
  if (m && method === 'GET') return fx.sheetMastery(m[1] ?? '');

  m = match(path, /^\/classes\/([^/]+)\/points$/);
  if (m && method === 'GET') return fx.classPoints(m[1] ?? '');

  m = match(path, /^\/classes\/([^/]+)\/tree$/);
  if (m && method === 'GET') return fx.classTree(m[1] ?? '');

  m = match(path, /^\/classes\/([^/]+)\/mastery$/);
  if (m && method === 'GET') {
    if (m[1] === state.classes[1]?.id) {
      return { ...fx.masteryMatrix, class_id: m[1], cells: [], competencies: [] };
    }
    return fx.classMastery(m[1] ?? '', query);
  }

  m = match(path, /^\/classes\/([^/]+)$/);
  if (m && method === 'GET') {
    const found = state.classes.find((c) => c.id === m?.[1]);
    if (!found) throw new ApiError(404, 'not_found', 'class not found');
    return found;
  }

  /* --------------------------------------- who teaches what (D75) --- */
  if (method === 'GET' && path === '/colleagues') return fx.colleagues;

  m = match(path, /^\/classes\/([^/]+)\/teachers$/);
  if (m && method === 'GET') return state.classTeachers[m[1] ?? ''] ?? [];

  m = match(path, /^\/classes\/([^/]+)\/teachers\/([^/]+)\/branches\/([^/]+)$/);
  if (m && (method === 'POST' || method === 'DELETE')) {
    const [, classId = '', teacherId = '', subjectId = ''] = m;
    const klass = requireClass(classId);
    if (method === 'POST') {
      // The API declares the branch first, so the composite FK can never
      // fire. The fixture has to do the same or it would accept an assignment
      // the real server refuses.
      if (!(klass.declared_subject_ids ?? []).includes(subjectId)) {
        throw new ApiError(422, 'unprocessable', 'this class does not study that branch');
      }
      assign(klass, teacherId, subjectId);
    } else {
      unassign(klass, teacherId, subjectId);
    }
    return state.classTeachers[classId] ?? [];
  }

  m = match(path, /^\/classes\/([^/]+)\/subjects\/([^/]+)$/);
  if (m && (method === 'POST' || method === 'DELETE')) {
    const [, classId = '', subjectId = ''] = m;
    const klass = requireClass(classId);
    if (method === 'POST') {
      if (!(klass.declared_subject_ids ?? []).includes(subjectId)) {
        klass.declared_subject_ids = [...(klass.declared_subject_ids ?? []), subjectId];
      }
      // Declaring assigns the caller too — otherwise a teacher would build a
      // sheet in a branch nobody has recorded them teaching and lose it.
      assign(klass, state.teacher.id, subjectId);
    } else {
      // Maths carries the fixture's sheets, so the refusal path is reachable
      // in the browser and not only in a unit test.
      const held = sheetsHeld(classId, subjectId);
      if (held > 0) {
        throw new ApiError(
          409,
          'branch_holds_sheets',
          'this branch still holds sheets in this class',
          { sheet_count: String(held) },
        );
      }
      klass.declared_subject_ids = (klass.declared_subject_ids ?? []).filter(
        (id) => id !== subjectId,
      );
      for (const row of state.classTeachers[classId] ?? []) {
        unassign(klass, row.teacher_id, subjectId);
      }
    }
    return klass;
  }

  m = match(path, /^\/classes\/([^/]+)\/subjects$/);
  if (m && method === 'PUT') {
    const klass = requireClass(m[1] ?? '');
    const asked = (body as { subject_ids?: string[] }).subject_ids ?? [];
    const declared = klass.declared_subject_ids ?? [];
    // Branches the caller did not name keep their place AFTER the ones they
    // did: the order belongs to the class, so a partial list from one
    // co-teacher must never drop another's branch.
    klass.declared_subject_ids = [
      ...asked.filter((id) => declared.includes(id)),
      ...declared.filter((id) => !asked.includes(id)),
    ];
    return klass;
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
      label: null,
      title: null,
      figure_url: null,
      figure_width_mm: null,
      figure_height_mm: null,
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
      fx.adaptive.plans
        .flatMap((p) => p.generated)
        .map((p) => p.exercise)
        .find((e) => e.id === m?.[1]);
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
    // And to a year, for the same reason `/classes` is: a sheet belongs to the
    // year of the class it was printed for, resolved through the class rather
    // than stored on the sheet — which is how the API answers it too.
    const yearId = query.get('school_year_id');
    const yearOf = (sheetClassId: string) =>
      state.classes.find((klass) => klass.id === sheetClassId)?.school_year_id ?? null;
    const all = Object.values(state.sheets)
      .filter((sheet) => (classId ? sheet.class_id === classId : true))
      .filter((sheet) => (yearId ? yearOf(sheet.class_id) === yearId : true));
    return all;
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
    // Resolved the way the GET below resolves it, so a render and a re-read
    // of the same URL cannot disagree about which sheet they mean.
    const target = state.sheets[sheetId] ?? state.sheets[fx.sheet.id];
    // What the worker does on the way back: both keys onto the sheet, and
    // `rendered_at`. The mock used to return the job and leave the sheet
    // untouched, so a rendered sheet never became a printable one here — and
    // the print gate (`lib/print.ts`), which reads exactly those fields, had
    // no reachable "ready" state in fixture mode. Mirrors the adaptive batch
    // render below, which already did this.
    if (target) {
      target.blank_pdf_url = `/mock/${sheetId}-blank.pdf`;
      target.answer_key_pdf_url = `/mock/${sheetId}-answer-key.pdf`;
      target.rendered_at = fx.NOW;
    }
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
  m = match(path, /^\/scans\/([^/]+)\/pages$/);
  if (m && method === 'POST') {
    const scanId = m[1] ?? '';
    const target = state.scans[scanId] ?? state.scans[fx.scan.id];
    if (!target) throw new ApiError(404, 'not_found', 'scan not found');
    // The retake supersedes the page it replaces, in the same request — the
    // server discards it in one transaction so the copy is never briefly
    // longer than it was printed.
    const superseded = body instanceof FormData ? body.get('supersedes_page_id') : null;
    if (typeof superseded === 'string') {
      const page = target.pages.find((candidate) => candidate.id === superseded);
      if (page) page.discarded = true;
    }
    return { ...target, job_id: startJob('process_scan', { scan_id: target.id }).id };
  }
  m = match(path, /^\/scans\/([^/]+)\/detections\/([^/]+)$/);
  if (m && method === 'PATCH') {
    const [, scanId, detectionId] = m;
    const target = state.scans[scanId ?? ''] ?? state.scans[fx.scan.id];
    if (!target) throw new ApiError(404, 'not_found', 'scan not found');
    for (const page of target.pages) {
      for (const detection of page.detections) {
        if (detection.id !== detectionId) continue;
        const correction = body as DetectionCorrection;
        if (detection.exercise_type === 'open') {
          if ('verdict_correct' in correction) {
            detection.verdict_correct = correction.verdict_correct ?? null;
          }
          if (correction.transcription != null) detection.transcription = correction.transcription;
        } else {
          detection.detected_index = correction.detected_index ?? null;
        }
        detection.outcome = 'corrected';
        detection.corrected_at = fx.NOW;
        detection.confidence = 1;
        return detection;
      }
    }
    throw new ApiError(404, 'not_found', 'detection not found');
  }
  m = match(path, /^\/scans\/([^/]+)\/students$/);
  if (m && method === 'GET') {
    // Who a page may be attributed to: the sheet's class, nobody else. This route
    // had no handler at all, so in fixture mode the list came back empty — which
    // left the page-assignment picker with no options and, once the review screen
    // started naming the pupil beside the code (G24), nothing to name them from.
    return fx.students;
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
    page.detected_uid = fx.students.find((s) => s.id === page.student_id)?.uid ?? page.detected_uid;
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
  // Planning is a JOB now, not a synchronous answer: the model calls run in the
  // worker. The mock has to agree with that, or the screen polls something the
  // fixture never made — which is how the export button shipped broken once
  // already (see e2e/adaptive.spec.ts).
  if (method === 'POST' && path === '/adaptive/propose') {
    const existing = Object.values(state.jobs).find(
      (job) => job.kind === 'propose_adaptive' && job.status !== 'succeeded',
    );
    if (existing) return stripTicks(existing);
    return startJob('propose_adaptive', { students: fx.adaptive.plans.length });
  }
  m = match(path, /^\/adaptive\/proposal\/([^/]+)$/);
  if (m && method === 'GET') {
    const job = state.jobs[m[1] ?? ''];
    if (!job || job.status !== 'succeeded') {
      throw new ApiError(404, 'not_found', 'proposal not built yet');
    }
    return currentProposal();
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
        points_earned: null,
        points_possible: 0,
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
