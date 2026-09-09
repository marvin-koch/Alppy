'use client';

import { Field, Select } from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { useEffect } from 'react';

import { useCurriculumTree } from '@/lib/api/queries';
import type { Uuid } from '@/lib/api/types';

interface Props {
  classId: Uuid | null;
  subjectId: Uuid | undefined;
  competencyId: Uuid | null;
  chapterId: Uuid | null;
  onCompetencyChange: (id: Uuid | null) => void;
  onChapterChange: (id: Uuid | null) => void;
}

/**
 * Two chained selects — Competence, then Theme — for narrowing a page that is
 * already showing something.
 *
 * Native selects rather than a custom tree widget, for the reason
 * `ScopeSwitcher` already gives: this has to be keyboard-first on a laptop and
 * a system picker on a phone, and neither is improved by re-implementing them.
 *
 * There is deliberately no "Sans thème" option here. That bucket answers
 * "which exercises did the book leave untagged", which is a question about the
 * corpus; this filter answers "which part of the programme am I looking at",
 * and mastery has no notion of an unfiled Theme. Offering it would put a
 * choice in the list that can only ever return an empty grid.
 */
export function CompetenceThemeFilter({
  classId,
  subjectId,
  competencyId,
  chapterId,
  onCompetencyChange,
  onChapterChange,
}: Props) {
  const tm = useTranslations('mastery');
  const locale = useLocale();
  const tree = useCurriculumTree(classId, subjectId ? { subjectId } : {});

  const branch = tree.data?.branches.find((b) => b.subject_id === subjectId) ?? null;
  const competences = branch?.competences ?? [];
  const selected = competences.find((c) => c.competency_id === competencyId) ?? null;
  // With no Competence chosen, every Theme in the Branch is offerable.
  const themes = selected ? selected.themes : competences.flatMap((c) => c.themes);

  // A stale id from the URL degrades to "everything", never to an arbitrary
  // node. `scope` deliberately does not validate these — it has no tree — so
  // the component that fetched one is the one that can.
  useEffect(() => {
    if (tree.isLoading || !branch) return;
    if (competencyId && !selected) onCompetencyChange(null);
    else if (chapterId && !themes.some((t) => t.chapter_id === chapterId)) {
      onChapterChange(null);
    }
  }, [
    tree.isLoading,
    branch,
    competencyId,
    selected,
    chapterId,
    themes,
    onCompetencyChange,
    onChapterChange,
  ]);

  const label = (labels: Record<string, string> | undefined, fallback: string) =>
    labels?.[locale] ?? labels?.fr ?? fallback;

  return (
    <>
      {/* Bounded width. A PER competence label is a full sentence ("Poser et
          résoudre des problèmes pour construire et structurer…"), and an
          unbounded select takes its intrinsic width from the longest option —
          which pushed this one onto a row of its own. */}
      <Field label={tm('filterCompetency')} className="w-full sm:w-64">
        <Select
          value={competencyId ?? ''}
          disabled={tree.isLoading || competences.length === 0}
          onChange={(event) => onCompetencyChange((event.target.value as Uuid) || null)}
        >
          <option value="">{tm('allCompetences')}</option>
          {competences.map((competence) => (
            <option key={competence.competency_id} value={competence.competency_id}>
              {competence.code} · {label(competence.labels, competence.code)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={tm('filterChapter')} className="w-full sm:w-56">
        <Select
          value={chapterId ?? ''}
          disabled={tree.isLoading || themes.length === 0}
          onChange={(event) => onChapterChange((event.target.value as Uuid) || null)}
        >
          <option value="">{tm('allChapters')}</option>
          {themes.map((theme) => (
            <option key={theme.chapter_id} value={theme.chapter_id}>
              {label(theme.labels, theme.key)}
            </option>
          ))}
        </Select>
      </Field>
    </>
  );
}
