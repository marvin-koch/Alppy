import { useMemo } from 'react';

import { useScope } from '@/lib/scope';
import type { ClassOut, Uuid } from '@/lib/api/types';

/**
 * The Branch to read a class through, and whether that was a real choice.
 *
 * Three class-scoped screens each carried their own copy of
 *
 *     scope.subjectId && ids.includes(scope.subjectId) ? scope.subjectId : ids[0]
 *
 * and the comment on the first one already admitted the bug: a class with two
 * Branches showed one of them with no way to see which. That is exactly the
 * case co-teaching makes ordinary (D73) — Camille takes maths AND French in
 * 7B — so the fallback stops being a rare edge and becomes the everyday path.
 *
 * One place now, and it reports what it did rather than hiding it. `fellBack`
 * is true when the rail's Branch is not one this teacher takes here, so the
 * screen can say which Branch it is showing instead of silently picking.
 *
 * `subjectId` is undefined when the caller takes NO Branch in this class — a
 * head teacher who teaches none. That is a real answer (an empty Programme,
 * with the roster still there), never a 404.
 */
export function useClassSubject(klass: ClassOut | undefined): {
  subjectId: Uuid | undefined;
  fellBack: boolean;
  choices: Uuid[];
} {
  const scope = useScope();
  return useMemo(() => {
    // `subject_ids` is what the CALLER takes here, already narrowed by the API.
    const choices = klass?.subject_ids ?? [];
    const chosen = scope.subjectId && choices.includes(scope.subjectId)
      ? scope.subjectId
      : undefined;
    return {
      subjectId: chosen ?? choices[0],
      fellBack: chosen === undefined && choices.length > 0,
      choices,
    };
  }, [klass?.subject_ids, scope.subjectId]);
}
