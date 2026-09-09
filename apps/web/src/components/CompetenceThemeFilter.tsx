'use client';

import { IconChevronDown, SelectSurface } from '@alppy/ui';
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
 * Only `/results` uses it. The class dashboard used to as well, beside a
 * `CurriculumTree` that draws the same hierarchy with a band on every node and
 * already filtered by Theme when you clicked one — two controls doing one job,
 * which is the duplication D45 argued against for the builder. There the tree
 * IS the filter now. `/results` has no tree, so it keeps a control.
 *
 * Native selects rather than a custom tree widget, for the reason
 * `ScopeSwitcher` already gives: this has to be keyboard-first on a laptop and
 * a system picker on a phone, and neither is improved by re-implementing them.
 * They read as a sentence rather than as two labelled boxes: the label is the
 * quiet half and the value is the loud one, and a control that is actually
 * narrowing something says so by carrying the action tint.
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
  const chosenTheme = themes.find((t) => t.chapter_id === chapterId) ?? null;

  const pill = (active: boolean) =>
    [
      'flex min-h-11 items-center gap-2 rounded-md border px-3',
      active
        ? 'border-primary-200 bg-primary-050 text-primary-700'
        : 'border-line bg-surface text-ink-900',
    ].join(' ');

  return (
    <>
      {/* Bounded width. A PER competence label is a full sentence ("Poser et
          résoudre des problèmes pour construire et structurer…"), and an
          unbounded select takes its intrinsic width from the longest option —
          which pushed this one onto a row of its own. */}
      <SelectSurface
        className="w-full rounded-md sm:w-72"
        label={tm('filterCompetency')}
        value={competencyId ?? ''}
        disabled={tree.isLoading || competences.length === 0}
        onChange={(value) => onCompetencyChange((value as Uuid) || null)}
        options={[
          { value: '', label: tm('allCompetences') },
          ...competences.map((competence) => ({
            value: competence.competency_id,
            label: `${competence.code} · ${label(competence.labels, competence.code)}`,
          })),
        ]}
      >
        <span className={pill(competencyId !== null)}>
          <span className="shrink-0 text-body-s text-ink-500">
            {tm('filterCompetency')}
          </span>
          <span className="min-w-0 flex-1 truncate text-body-s font-semibold">
            {selected ? selected.code : tm('allCompetences')}
          </span>
          <IconChevronDown size={16} className="shrink-0 text-ink-500" />
        </span>
      </SelectSurface>

      <SelectSurface
        className="w-full rounded-md sm:w-64"
        label={tm('filterChapter')}
        value={chapterId ?? ''}
        disabled={tree.isLoading || themes.length === 0}
        onChange={(value) => onChapterChange((value as Uuid) || null)}
        options={[
          { value: '', label: tm('allChapters') },
          ...themes.map((theme) => ({
            value: theme.chapter_id,
            label: label(theme.labels, theme.key),
          })),
        ]}
      >
        <span className={pill(chapterId !== null)}>
          <span className="shrink-0 text-body-s text-ink-500">
            {tm('filterChapter')}
          </span>
          <span className="min-w-0 flex-1 truncate text-body-s font-semibold">
            {chosenTheme ? label(chosenTheme.labels, chosenTheme.key) : tm('allChapters')}
          </span>
          <IconChevronDown size={16} className="shrink-0 text-ink-500" />
        </span>
      </SelectSurface>
    </>
  );
}
