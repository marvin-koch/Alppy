'use client';

import { createContext, useContext } from 'react';

import type { SchoolYearOut, Uuid } from '@/lib/api/types';

/**
 * The selected school year, as a context and nothing else.
 *
 * Split from `school-year.tsx` for the import graph, which is the whole reason
 * this dimension is its own module in the first place. `lib/api/queries` reads
 * the selected year, and the PROVIDER needs the router (`@/i18n/navigation`) to
 * read and write `?year=`. Leaving them together made `queries.ts` — and so
 * every consumer of `queryKeys`, including its unit test — transitively require
 * a Next router it has no business knowing about.
 *
 * So: the context, its type and its reader live here and import nothing beyond
 * React and the API types. The provider lives next door.
 */
export interface SelectedYear {
  /** The id to filter by, or null while the list is still arriving. */
  schoolYearId: Uuid | null;
  /**
   * The moment mastery is computed at, or `undefined` for "now".
   *
   * This is the `as_of` the API added, and it is a DIFFERENT parameter from
   * `school_year_id`: the id says which year's objects to list, `as_of` rewinds
   * the mastery model — attempts after it are dropped, the decay is measured to
   * it, and the roster moves with it (`api/v1/mastery.py`). Selecting a past year
   * and leaving `as_of` at "now" would decay every one of that year's attempts by
   * however long ago it ended, and show a class that had learnt nothing.
   *
   * End of the last day, not the date itself: `ends_on` alone parses to midnight
   * and would drop everything recorded on the final day of the year.
   */
  asOf: string | undefined;
  years: SchoolYearOut[];
  currentYear: SchoolYearOut | null;
  selectedYear: SchoolYearOut | null;
  /** True when the teacher is looking at a year that is not the current one. */
  isPastYear: boolean;
  setSchoolYear: (id: Uuid) => void;
  isLoading: boolean;
}

const INERT: SelectedYear = {
  schoolYearId: null,
  asOf: undefined,
  years: [],
  currentYear: null,
  selectedYear: null,
  isPastYear: false,
  setSchoolYear: () => {},
  isLoading: false,
};

export const SchoolYearContext = createContext<SelectedYear | null>(null);

/**
 * The selected year.
 *
 * Returns an inert value outside the provider rather than throwing, so the login
 * screen and any chromeless route work unchanged — and so `queries.ts` can call
 * it unconditionally without every hook needing to know where it is mounted.
 */
export function useSelectedYear(): SelectedYear {
  return useContext(SchoolYearContext) ?? INERT;
}
