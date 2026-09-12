'use client';

import { Button, IconChevronDown, Modal, Panel } from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useCurriculumTree } from '@/lib/api/queries';
import { competenceCodes } from '@/lib/competenceCode';
import type { TreeThemeOut, Uuid } from '@/lib/api/types';

/**
 * The builder's root: which Theme is this sheet about.
 *
 * `'unfiled'` is a CLIENT-SIDE pseudo-node, and it is not the same thing as
 * the `unfiled` Chapter the API keeps for legacy sheets. This one means
 * "show me the exercises the book left untagged"; that one is where an
 * unfiled sheet is stored. A sheet can never be filed under this selection —
 * see `canFile` below — it only ever narrows the exercise list.
 */
export type ThemeSelection = TreeThemeOut | 'unfiled' | null;

/** Whether a selection is something a sheet may actually be filed under. */
export function canFile(selection: ThemeSelection): selection is TreeThemeOut {
  return selection !== null && selection !== 'unfiled';
}

interface Props {
  classId: Uuid | null;
  subjectId: Uuid | undefined;
  selection: ThemeSelection;
  onSelect: (selection: ThemeSelection) => void;
  /** Exercises in this Branch with no chapter at all. */
  unfiledExerciseCount: number;
}

export function ThemePicker({
  classId,
  subjectId,
  selection,
  onSelect,
  unfiledExerciseCount,
}: Props) {
  const t = useTranslations('builder');
  const tc = useTranslations('common');
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const tree = useCurriculumTree(classId, subjectId ? { subjectId } : {});

  const branch = tree.data?.branches.find((b) => b.subject_id === subjectId) ?? null;
  // Two editions of one curriculum code are two Competences carrying the same
  // code and the same sentence, each with its own Themes. The edition is shown
  // only on the rows where that collision is real.
  const codeOf = competenceCodes(branch?.competences ?? []);
  const label = (labels: Record<string, string> | undefined, fallback: string) =>
    labels?.[locale] ?? labels?.fr ?? fallback;

  const summary = canFile(selection)
    ? label(selection.labels, selection.key)
    : selection === 'unfiled'
      ? t('unfiledBucket', { count: unfiledExerciseCount })
      : t('themePlaceholder');

  const choose = (next: ThemeSelection) => {
    onSelect(next);
    setOpen(false);
  };

  return (
    <>
      <Panel className="flex flex-wrap items-center gap-3">
        <span className="text-label text-ink-500">{t('theme')}</span>
        <span className="min-w-0 flex-1 truncate font-display text-body-l font-semibold">
          {summary}
        </span>
        <Button onClick={() => setOpen(true)}>{t('changeTheme')}</Button>
      </Panel>

      <Modal
        open={open}
        onOpenChange={setOpen}
        title={t('themeModalTitle')}
        closeLabel={tc('close')}
        size="lg"
      >
        <div className="flex flex-col gap-5">
          {(branch?.competences ?? []).map((competence) => (
            <section key={competence.competency_id} className="flex flex-col gap-2">
              <header className="flex min-h-11 items-center gap-2 px-1">
                <IconChevronDown size={16} className="shrink-0 text-ink-500" aria-hidden />
                <span className="font-mono text-label text-ink-700">
                  {codeOf.get(competence.competency_id) ?? competence.code}
                </span>
                <h3 className="min-w-0 flex-1 truncate text-body-s font-bold text-ink-700">
                  {label(competence.labels, competence.code)}
                </h3>
              </header>
              <ul className="m-0 ml-6 flex list-none flex-col gap-2 p-0">
                {competence.themes.map((theme) => {
                  const active = canFile(selection) && selection.chapter_id === theme.chapter_id;
                  return (
                    <li key={theme.chapter_id}>
                      <button
                        type="button"
                        onClick={() => choose(theme)}
                        aria-current={active ? 'true' : undefined}
                        className="flex min-h-11 w-full items-center gap-3 rounded-md border border-line px-3 py-2 text-left transition-colors hover:bg-primary-050 aria-[current=true]:border-primary-500 aria-[current=true]:bg-primary-050"
                      >
                        <span className="min-w-0 flex-1 truncate text-body-l font-semibold">
                          {label(theme.labels, theme.key)}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}

          {/*
            The load-bearing row.

            ExercisePicker used to guarantee "nothing is unreachable" by NOT
            filtering on theme at all, because `Exercise.chapter_id` is
            inferred and null on a large minority of a real textbook's rows.
            Now that Theme is the builder's root, that guarantee has to be kept
            by design instead — so this row is pinned at the ROOT of the tree,
            sibling to every Competence rather than buried inside one, and is
            rendered even when the count is zero. Removing it, or hiding it on
            zero, silently loses exercises again.
          */}
          <button
            type="button"
            onClick={() => choose('unfiled')}
            aria-current={selection === 'unfiled' ? 'true' : undefined}
            className="flex min-h-11 w-full items-center gap-3 rounded-md border border-dashed border-line-strong bg-surface-2 px-3 py-2 text-left transition-colors hover:bg-primary-050 aria-[current=true]:border-primary-500"
          >
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="truncate text-body-l font-semibold text-ink-700">
                {t('unfiledBucket', { count: unfiledExerciseCount })}
              </span>
              <span className="text-body-s text-ink-500">{t('unfiledBucketHelp')}</span>
            </span>
          </button>

          <p className="text-body-s text-ink-500">{t('unfiledCannotFile')}</p>
        </div>
      </Modal>
    </>
  );
}
