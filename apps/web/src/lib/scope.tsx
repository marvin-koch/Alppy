'use client';

import { useParams, useSearchParams } from 'next/navigation';
// next-intl's `usePathname` has the locale prefix stripped and its `useRouter`
// puts one back on. Mixing in `next/navigation`'s pathname here produced
// `/fr/fr?class=…` — the locale applied twice.
import { usePathname, useRouter } from '@/i18n/navigation';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  type ReactNode,
} from 'react';

import { useClasses, useMe, useSubjects } from '@/lib/api/queries';
import type { ClassOut, SubjectOut, Uuid } from '@/lib/api/types';

/**
 * The class and subject every screen is scoped to.
 *
 * The URL is the source of truth (`?class=…&subject=…`), for one reason: a
 * teacher sends a colleague a link to a matrix, and a context that lived only
 * in memory or in localStorage would open somebody else's default instead.
 * localStorage is the *fallback*, so that arriving at a bare `/fr/sheets/new`
 * still lands on the class you were last working in rather than on whichever
 * one sorts first alphabetically.
 *
 * Both values are validated against what the API actually returns before they
 * are used. A stored id can outlive its class — the class was deleted, or the
 * teacher no longer owns it (decisions-log D23) — and a stale id must degrade
 * to "the first class you do have", never to a request that 404s.
 */
export interface ScopeValue {
  classId: Uuid | null;
  subjectId: Uuid | null;
  /**
   * The Competence and Theme in view, from `?competency=` and `?chapter=`.
   *
   * Deliberately NOT resolved the way class and subject are. `resolve()` falls
   * back to "the first one you have", which is right for a class — some class
   * must always be showing — and wrong here: the correct default for a filter
   * is "everything", so a stale or unknown id must degrade to null, never to
   * an arbitrary chapter that silently narrows a matrix.
   *
   * They are also NOT persisted. "Which class am I teaching" is sticky across
   * sessions; "which chapter was I looking at yesterday" is not, and a
   * remembered one would silently re-root a fresh sheet builder.
   *
   * Validating them against real data belongs to whichever component fetched
   * the tree, not here — `ScopeProvider` must not fetch a curriculum tree on
   * every route, including the ones that never render one.
   */
  competencyId: Uuid | null;
  chapterId: Uuid | null;
  classes: ClassOut[];
  /**
   * The Branches the teacher takes in `currentClass`, in the class's order —
   * NOT every Branch the school has. Narrowed since D73: a switcher offering
   * a Branch you do not teach here lands on an empty tree with nothing to say
   * why. Falls back to the school list only before a class has resolved.
   */
  /**
   * The school this session acts for. Read-only here: switching is a server
   * round-trip that re-issues the cookie (D74), so it lives in
   * `useSwitchSchool`, not in a setter that only moved a query param.
   */
  schoolId: Uuid | null;
  subjects: SubjectOut[];
  currentClass: ClassOut | null;
  currentSubject: SubjectOut | null;
  setClass: (id: Uuid) => void;
  setSubject: (id: Uuid) => void;
  setCompetency: (id: Uuid | null) => void;
  setChapter: (id: Uuid | null) => void;
  /** True until the class list has arrived; the switcher renders disabled. */
  isLoading: boolean;
}

const ScopeContext = createContext<ScopeValue | null>(null);

const STORAGE_KEY = 'alppy.scope';

interface StoredScope {
  classId?: string;
  subjectId?: string;
}

function readStored(): StoredScope {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as StoredScope) : {};
  } catch {
    // A private window, or storage blocked. The URL still works.
    return {};
  }
}

function writeStored(next: StoredScope): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* not worth interrupting the teacher for */
  }
}

/** The first id that actually exists in `available`, else the first available. */
function resolve<T extends { id: string }>(
  available: T[],
  ...candidates: (string | null | undefined)[]
): T | null {
  for (const candidate of candidates) {
    if (!candidate) continue;
    const hit = available.find((item) => item.id === candidate);
    if (hit) return hit;
  }
  return available[0] ?? null;
}

export function ScopeProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const routeParams = useParams();

  // The login screen is outside the session, so asking there would only
  // produce a 401 for every visitor who is not signed in yet.
  const enabled = pathname !== '/login';
  const classesQuery = useClasses(enabled);
  const subjectsQuery = useSubjects(enabled);
  const me = useMe(enabled);
  const classes = useMemo(() => classesQuery.data ?? [], [classesQuery.data]);
  const subjects = useMemo(() => subjectsQuery.data ?? [], [subjectsQuery.data]);

  // `/classes/[classId]` names its class in the path. That is more specific
  // than a query string, so it wins — otherwise opening a class from the home
  // screen would show one class while the switcher claimed another.
  const pathClassId =
    typeof routeParams?.classId === 'string' ? routeParams.classId : undefined;

  const stored = readStored();
  const currentClass = resolve(
    classes,
    pathClassId,
    searchParams.get('class'),
    stored.classId,
  );
  // The Branches this teacher takes IN THE SELECTED CLASS, in the class's own
  // order — not every Branch the school has.
  //
  // `ClassOut.subject_ids` means "mine here" (D73): a class may study history
  // without this teacher taking it. Resolving against the school-wide list let
  // the switcher offer a Branch the caller does not teach in the class they are
  // looking at, which lands on an empty tree with nothing to say why.
  //
  // Falls back to the school list only while no class has resolved yet, so the
  // switcher is never briefly empty on a cold load. An empty result once a
  // class HAS resolved is a real answer, not a gap: a maitre de classe who
  // teaches nothing here gets a roster and no Branch level.
  const classSubjects = useMemo(() => {
    if (!currentClass) return subjects;
    return currentClass.subject_ids
      .map((id) => subjects.find((subject) => subject.id === id))
      .filter((subject): subject is SubjectOut => subject !== undefined);
  }, [currentClass, subjects]);
  const currentSubject = resolve(
    classSubjects,
    searchParams.get('subject'),
    stored.subjectId,
  );
  // The tenant, for anything that needs to key a cache or a link by it. It is
  // NOT resolved the way class and subject are: the server decides it, and a
  // `?school=` that disagreed with the cookie would be a lie the client told
  // itself.
  const schoolId = (me.data?.school_id ?? null) as Uuid | null;
  // Plain reads: no resolve(), no storage, no "first one" fallback. See the
  // note on ScopeValue for why these two are different from the pair above.
  const competencyId = searchParams.get('competency');
  const chapterId = searchParams.get('chapter');

  // Persist whatever we settled on, so the next bare route reopens here.
  //
  // Two things this has to get right, both learned the hard way. Wait until
  // BOTH lists have arrived: resolving against an empty list yields "the first
  // one", and writing that would overwrite a perfectly good stored id with a
  // default. And MERGE rather than replace: subjects usually resolve before
  // classes, and writing `{subjectId}` alone dropped `classId` from storage, so
  // the next bare route silently fell back to the alphabetically first class.
  useEffect(() => {
    if (classesQuery.isLoading || subjectsQuery.isLoading) return;
    if (!currentClass && !currentSubject) return;
    writeStored({
      ...readStored(),
      ...(currentClass ? { classId: currentClass.id } : {}),
      ...(currentSubject ? { subjectId: currentSubject.id } : {}),
    });
  }, [currentClass, currentSubject, classesQuery.isLoading, subjectsQuery.isLoading]);

  const push = useCallback(
    (key: 'class' | 'subject' | 'competency' | 'chapter', id: Uuid) => {
      const next = new URLSearchParams(searchParams.toString());
      next.set(key, id);
      // `replace`, not `push`: switching class is changing what you are looking
      // at, not a step to come back to with the Back button.
      router.replace(`${pathname}?${next.toString()}`);
    },
    [pathname, router, searchParams],
  );

  const setClass = useCallback(
    (id: Uuid) => {
      writeStored({ ...readStored(), classId: id });
      // A class-detail URL names its class in the path; switching class there
      // has to move to the other class's page, not bolt a contradicting query
      // string onto this one.
      if (pathClassId) {
        const next = new URLSearchParams(searchParams.toString());
        next.delete('class');
        const qs = next.toString();
        router.replace(`/classes/${id}${qs ? `?${qs}` : ''}`);
        return;
      }
      push('class', id);
    },
    [pathClassId, push, router, searchParams],
  );

  const setSubject = useCallback(
    (id: Uuid) => {
      writeStored({ ...readStored(), subjectId: id });
      // A Competence and a Theme belong to exactly one Branch, so carrying
      // either across a subject change would filter on another subject's
      // curriculum — the same reason the builder already clears its source and
      // section here.
      const next = new URLSearchParams(searchParams.toString());
      next.set('subject', id);
      next.delete('competency');
      next.delete('chapter');
      router.replace(`${pathname}?${next.toString()}`);
    },
    [pathname, router, searchParams],
  );

  const setParam = useCallback(
    (key: 'competency' | 'chapter', id: Uuid | null) => {
      const next = new URLSearchParams(searchParams.toString());
      if (id === null) next.delete(key);
      else next.set(key, id);
      // A Theme belongs to one Competence; changing the Competence cannot
      // leave a Theme from the previous one selected underneath it.
      if (key === 'competency') next.delete('chapter');
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname);
    },
    [pathname, router, searchParams],
  );

  const setCompetency = useCallback(
    (id: Uuid | null) => setParam('competency', id),
    [setParam],
  );
  const setChapter = useCallback((id: Uuid | null) => setParam('chapter', id), [setParam]);

  const value = useMemo<ScopeValue>(
    () => ({
      schoolId,
      classId: currentClass?.id ?? null,
      subjectId: currentSubject?.id ?? null,
      competencyId,
      chapterId,
      classes,
      subjects: classSubjects,
      currentClass,
      currentSubject,
      setClass,
      setSubject,
      setCompetency,
      setChapter,
      isLoading: classesQuery.isLoading || subjectsQuery.isLoading,
    }),
    [
      schoolId,
      classes,
      classSubjects,
      currentClass,
      currentSubject,
      competencyId,
      chapterId,
      setClass,
      setSubject,
      setCompetency,
      setChapter,
      classesQuery.isLoading,
      subjectsQuery.isLoading,
    ],
  );

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}

/**
 * The current class and subject.
 *
 * Returns an inert scope outside the provider (the login screen) rather than
 * throwing, so a chromeless route does not have to special-case it.
 */
export function useScope(): ScopeValue {
  const ctx = useContext(ScopeContext);
  if (ctx) return ctx;
  return {
    classId: null,
    subjectId: null,
    competencyId: null,
    chapterId: null,
    classes: [],
    schoolId: null,
    subjects: [],
    currentClass: null,
    currentSubject: null,
    setClass: () => {},
    setSubject: () => {},
    setCompetency: () => {},
    setChapter: () => {},
    isLoading: false,
  };
}
