'use client';

import { useCallback, useMemo, useState } from 'react';

import { SHEET_LAYOUT } from '@alppy/shared';

import { ITEMS_PER_PAGE } from '@/lib/optionLetters';
import type { AnswerBoxFill, AnswerBoxLines, ExerciseOut, SheetItemIn, Uuid } from '@/lib/api/types';

/** `SheetCreate.items` is capped here by the API. */
export const MAX_SHEET_ITEMS = 64;

/** The box heights the paper reserves room for, straight from `layout.py`. */
export const ANSWER_BOX_LINES: readonly AnswerBoxLines[] = [
  0,
  ...(SHEET_LAYOUT.answerBox.linePresets as readonly AnswerBoxLines[]),
];
export const DEFAULT_ANSWER_BOX_LINES = SHEET_LAYOUT.answerBox.defaultLines as AnswerBoxLines;
export const ANSWER_BOX_FILLS: readonly AnswerBoxFill[] = ['lined', 'grid', 'blank'];
export const DEFAULT_ANSWER_BOX_FILL: AnswerBoxFill = 'lined';

export interface AnswerBox {
  lines: AnswerBoxLines;
  fill: AnswerBoxFill;
}

export interface DraftItem {
  exercise: ExerciseOut;
  /** The teacher's printed wording. Rides along as `SheetItem.statement_override`,
   *  so the corpus keeps its own text and its provenance. */
  override?: string;
  /** The written-answer box under an open item. Absent means the default;
   *  meaningless on a bubble item and never sent for one. */
  box?: AnswerBox;
}

/** The box an item prints, defaults applied. */
export function answerBoxOf(item: DraftItem): AnswerBox {
  return item.box ?? { lines: DEFAULT_ANSWER_BOX_LINES, fill: DEFAULT_ANSWER_BOX_FILL };
}

/**
 * One draft item as the API takes it, for the preview and for creation alike —
 * one place, so the paper the teacher previews is the paper they print.
 */
export function toSheetItemIn(item: DraftItem, position: number): SheetItemIn {
  return {
    exercise_id: item.exercise.id,
    position,
    ...(item.override ? { statement_override: item.override } : {}),
    ...(item.exercise.type === 'open' && item.box
      ? { answer_box_lines: item.box.lines, answer_box_fill: item.box.fill }
      : {}),
  };
}

export interface DraftSheet {
  items: DraftItem[];
  ids: Set<Uuid>;
  count: number;
  isFull: boolean;
  /** How many physical pages the answer grid forces, at minimum.
   *
   *  Not the real pagination — that also depends on statement height and lives
   *  in `sheets/pagination.py`, which is why the server preview is the
   *  authority. This is the floor, and it is enough to stop a teacher ticking
   *  forty exercises while the preview is closed. */
  minPages: number;
  has: (id: Uuid) => boolean;
  toggle: (exercise: ExerciseOut) => void;
  add: (exercise: ExerciseOut) => void;
  remove: (id: Uuid) => void;
  move: (index: number, delta: number) => void;
  reorder: (from: number, to: number) => void;
  setOverride: (id: Uuid, value: string | undefined) => void;
  setAnswerBox: (id: Uuid, box: Partial<AnswerBox>) => void;
  clear: () => void;
}

/**
 * The sheet the teacher is building.
 *
 * Deliberately independent of whatever the picker is currently showing. The
 * picker is a *viewport* onto a document that may hold a thousand exercises,
 * and it repaginates and refilters constantly; if the selection lived in the
 * visible list, changing a filter would silently drop what the teacher had
 * already ticked. So this holds whole `ExerciseOut` objects rather than ids —
 * an item stays on the sheet, renderable, after its page of the picker is long
 * gone.
 */
export function useDraftSheet(): DraftSheet {
  const [items, setItems] = useState<DraftItem[]>([]);

  const ids = useMemo(() => new Set(items.map((i) => i.exercise.id)), [items]);

  const has = useCallback((id: Uuid) => ids.has(id), [ids]);

  const add = useCallback((exercise: ExerciseOut) => {
    setItems((current) => {
      if (current.some((i) => i.exercise.id === exercise.id)) return current;
      if (current.length >= MAX_SHEET_ITEMS) return current;
      return [...current, { exercise }];
    });
  }, []);

  const remove = useCallback((id: Uuid) => {
    setItems((current) => current.filter((i) => i.exercise.id !== id));
  }, []);

  const toggle = useCallback((exercise: ExerciseOut) => {
    setItems((current) => {
      if (current.some((i) => i.exercise.id === exercise.id)) {
        return current.filter((i) => i.exercise.id !== exercise.id);
      }
      if (current.length >= MAX_SHEET_ITEMS) return current;
      return [...current, { exercise }];
    });
  }, []);

  const reorder = useCallback((from: number, to: number) => {
    setItems((current) => {
      if (from === to || from < 0 || to < 0) return current;
      if (from >= current.length || to >= current.length) return current;
      const next = [...current];
      const [moved] = next.splice(from, 1);
      if (moved) next.splice(to, 0, moved);
      return next;
    });
  }, []);

  const move = useCallback(
    (index: number, delta: number) => reorder(index, index + delta),
    [reorder],
  );

  const setOverride = useCallback((id: Uuid, value: string | undefined) => {
    setItems((current) =>
      current.map((item) =>
        item.exercise.id === id
          ? {
              exercise: item.exercise,
              ...(value ? { override: value } : {}),
              ...(item.box ? { box: item.box } : {}),
            }
          : item,
      ),
    );
  }, []);

  const setAnswerBox = useCallback((id: Uuid, box: Partial<AnswerBox>) => {
    setItems((current) =>
      current.map((item) =>
        item.exercise.id === id ? { ...item, box: { ...answerBoxOf(item), ...box } } : item,
      ),
    );
  }, []);

  const clear = useCallback(() => setItems([]), []);

  return {
    items,
    ids,
    count: items.length,
    isFull: items.length >= MAX_SHEET_ITEMS,
    minPages: Math.max(1, Math.ceil(items.length / ITEMS_PER_PAGE)),
    has,
    toggle,
    add,
    remove,
    move,
    reorder,
    setOverride,
    setAnswerBox,
    clear,
  };
}

/**
 * The sheet's language: the one its exercises are written in.
 *
 * Not the interface locale. Exercise content follows the language of the source
 * material (CLAUDE.md), and taking `items[0]` meant reordering could flip a
 * French sheet to German.
 */
export function draftLanguage(items: DraftItem[], fallback: string): 'fr' | 'de' | 'en' {
  const counts = new Map<string, number>();
  for (const item of items) {
    const language = item.exercise.language;
    if (language) counts.set(language, (counts.get(language) ?? 0) + 1);
  }
  let best: string | null = null;
  for (const [language, n] of counts) {
    if (best === null || n > (counts.get(best) ?? 0)) best = language;
  }
  return (best ?? fallback) as 'fr' | 'de' | 'en';
}

export function draftHasMixedLanguages(items: DraftItem[]): boolean {
  return new Set(items.map((i) => i.exercise.language).filter(Boolean)).size > 1;
}
