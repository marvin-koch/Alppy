'use client';

import { useCallback, useEffect, useMemo, type ReactNode } from 'react';
import { useSearchParams } from 'next/navigation';

import { usePathname, useRouter } from '@/i18n/navigation';
import type { SchoolYearOut, Uuid } from '@/lib/api/types';
import { SchoolYearContext, type SelectedYear } from '@/lib/school-year-context';

// Re-exported so app code has one import path for the whole dimension.
export { useSelectedYear } from '@/lib/school-year-context';
export type { SelectedYear } from '@/lib/school-year-context';

/**
 * Which school year every screen below is reading.
 *
 * Its own module, and its own provider, for two reasons that both matter.
 *
 * **The cycle.** `lib/scope.tsx` imports `useClasses` from `lib/api/queries`, so
 * `queries` cannot import `scope`. But the year has to reach the hooks — every
 * `queryKey` and every request needs it — and threading it through eighteen call
 * sites means eighteen chances to forget one, on a dimension whose failure mode is
 * a teacher reading last year's numbers as this year's. So the year lives here,
 * this module imports nothing from `queries`, and `queries` imports
 * `useSelectedYear`. No cycle, and no screen can leave it out.
 *
 * **It is not a filter.** Class, subject, Competence and Theme narrow what you
 * are looking at within one context. The year changes the context itself: it
 * moves the roster, the sheets, the piles and the mastery all at once. Keeping it
 * beside them in `ScopeValue` would have invited the same "just another chip"
 * treatment, and this is the one selection that must never be quiet.
 *
 * Sticky, like class and subject: "which year am I teaching" survives a session.
 * `?year=` still wins, so a link a teacher sends a colleague opens the year they
 * meant.
 */
const STORAGE_KEY = 'alppy.schoolYear';

function readStored(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(id: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* a private window; the URL still works */
  }
}

/** `ends_on` at the end of its last day, naive — the API reads a naive datetime
 *  as UTC (`mastery_service._now`). */
function endOfYear(year: SchoolYearOut): string {
  return `${year.ends_on}T23:59:59`;
}

/**
 * The provider.
 *
 * Takes the year list as a prop rather than fetching it, so this module stays
 * free of `queries` and the cycle described above cannot come back. `Providers`
 * owns the fetch.
 */
export function SchoolYearProvider({
  years,
  isLoading,
  children,
}: {
  years: SchoolYearOut[];
  isLoading: boolean;
  children: ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const currentYear = useMemo(() => years.find((y) => y.is_current) ?? null, [years]);

  // Resolved, not trusted. A stored id outlives the year it named — a school
  // rolls over, an establishment is left — and a stale one must degrade to the
  // CURRENT year, never to "the first in the list", which after a rollover is
  // whichever end of the ordering the API happened to return.
  const requested = searchParams.get('year') ?? readStored();
  const selectedYear = useMemo(() => {
    const hit = requested ? years.find((y) => y.id === requested) : undefined;
    return hit ?? currentYear ?? years[0] ?? null;
  }, [requested, years, currentYear]);

  // Persist only once the list has arrived: resolving against an empty list
  // yields the fallback, and writing that would overwrite a good stored id with
  // a default — the same trap `lib/scope.tsx` documents for class and subject.
  useEffect(() => {
    if (isLoading || !selectedYear) return;
    writeStored(selectedYear.id);
  }, [isLoading, selectedYear]);

  const setSchoolYear = useCallback(
    (id: Uuid) => {
      writeStored(id);
      const next = new URLSearchParams(searchParams.toString());
      next.set('year', id);
      // A Competence and a Theme belong to one year's curriculum view, and a
      // sheet or a pile named in the query string belongs to one year's data.
      // Carrying either across would point at something the new year does not
      // contain — the same reason `setSubject` clears them.
      next.delete('competency');
      next.delete('chapter');
      // `replace`, like every other scope change: choosing a year is changing
      // what you are looking at, not a step to come back to with Back.
      router.replace(`${pathname}?${next.toString()}`);
    },
    [pathname, router, searchParams],
  );

  const isPastYear = Boolean(selectedYear && currentYear && selectedYear.id !== currentYear.id);

  const value = useMemo<SelectedYear>(
    () => ({
      schoolYearId: (selectedYear?.id ?? null) as Uuid | null,
      // Undefined for the current year: "now" is what every read meant before
      // this existed, and sending today's date instead would be a behaviour
      // change dressed as a no-op.
      asOf: isPastYear && selectedYear ? endOfYear(selectedYear) : undefined,
      years,
      currentYear,
      selectedYear,
      isPastYear,
      setSchoolYear,
      isLoading,
    }),
    [selectedYear, isPastYear, years, currentYear, setSchoolYear, isLoading],
  );

  return <SchoolYearContext.Provider value={value}>{children}</SchoolYearContext.Provider>;
}
