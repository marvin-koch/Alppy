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

import { useClasses, useSubjects } from '@/lib/api/queries';
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
  classes: ClassOut[];
  subjects: SubjectOut[];
  currentClass: ClassOut | null;
  currentSubject: SubjectOut | null;
  setClass: (id: Uuid) => void;
  setSubject: (id: Uuid) => void;
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
  const currentSubject = resolve(subjects, searchParams.get('subject'), stored.subjectId);

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
    (key: 'class' | 'subject', id: Uuid) => {
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
      push('subject', id);
    },
    [push],
  );

  const value = useMemo<ScopeValue>(
    () => ({
      classId: currentClass?.id ?? null,
      subjectId: currentSubject?.id ?? null,
      classes,
      subjects,
      currentClass,
      currentSubject,
      setClass,
      setSubject,
      isLoading: classesQuery.isLoading || subjectsQuery.isLoading,
    }),
    [
      classes,
      subjects,
      currentClass,
      currentSubject,
      setClass,
      setSubject,
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
    classes: [],
    subjects: [],
    currentClass: null,
    currentSubject: null,
    setClass: () => {},
    setSubject: () => {},
    isLoading: false,
  };
}
