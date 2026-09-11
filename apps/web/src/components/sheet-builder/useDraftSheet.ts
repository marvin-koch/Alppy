'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

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
/** The tallest box a page can carry on its own; the API refuses more. */
export const MAX_ANSWER_BOX_LINES = SHEET_LAYOUT.answerBox.maxLines as number;

/** Clamp a typed height to what the paper can print. */
export function clampAnswerBoxLines(value: number): AnswerBoxLines {
  if (!Number.isFinite(value)) return DEFAULT_ANSWER_BOX_LINES;
  return Math.min(MAX_ANSWER_BOX_LINES, Math.max(0, Math.round(value)));
}
export const ANSWER_BOX_FILLS: readonly AnswerBoxFill[] = ['lined', 'grid', 'blank'];
export const DEFAULT_ANSWER_BOX_FILL: AnswerBoxFill = 'lined';

/** The barème, straight from `layout.py`. */
export const DEFAULT_POINTS_CORRECT = SHEET_LAYOUT.grading.defaultPointsCorrect as number;
export const DEFAULT_POINTS_PENALTY = SHEET_LAYOUT.grading.defaultPointsPenalty as number;
/** The most a single item may be worth; the API refuses more. */
export const MAX_ITEM_POINTS = SHEET_LAYOUT.grading.maxItemPoints as number;

/** The shortcuts the control offers. Any value in 0..MAX_ITEM_POINTS is legal;
 *  these are the ones a teacher reaches for. */
export const POINTS_PRESETS: readonly number[] = [0.5, 1, 2, 3, 5];
export const PENALTY_PRESETS: readonly number[] = [0, 0.25, 0.5, 1];

/** Clamp a typed value to what the API will accept. */
export function clampPoints(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_POINTS_CORRECT;
  return Math.min(MAX_ITEM_POINTS, Math.max(0, Math.round(value * 100) / 100));
}

/** The barème a whole sheet grades by, and every item falls back to. */
export interface Bareme {
  /** What a correct answer earns. */
  correct: number;
  /** What a wrong answer costs, as a MAGNITUDE — the server applies the sign.
   *  A blank is never penalised, whatever this is. */
  penalty: number;
}

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
  /** The answer the teacher expects for this printing of an open item. Rides
   *  along as `SheetItem.expected_answer`. Absent means the exercise's own
   *  answer if it has one, else the grader works it out itself. */
  expectedAnswer?: string;
  /** This item's own barème, when it departs from the sheet's. Absent means it
   *  follows the sheet — so changing the sheet's barème moves it, which is the
   *  behaviour a teacher expects from a default. */
  points?: Partial<Bareme>;
}

/** The answer an open item will be judged against, as the builder shows it:
 *  the teacher's for this sheet, else the one the exercise already carries. */
export function expectedAnswerOf(item: DraftItem): string {
  return item.expectedAnswer ?? item.exercise.answer_text ?? '';
}

/** What an item is worth: its own override, else the sheet's barème.
 *
 *  Tested against `undefined` rather than for truth, exactly as the server
 *  tests `is not None`: 0 is a real choice — an item that earns nothing, or one
 *  that costs nothing to get wrong — and reading it as absent would silently
 *  hand the item the sheet's value back. */
export function baremeOf(item: DraftItem, sheet: Bareme): Bareme {
  return {
    correct: item.points?.correct ?? sheet.correct,
    penalty: item.points?.penalty ?? sheet.penalty,
  };
}

/** Whether this item departs from the sheet's barème at all. */
export function hasOwnBareme(item: DraftItem): boolean {
  return item.points?.correct !== undefined || item.points?.penalty !== undefined;
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
    ...(item.exercise.type === 'open' && item.expectedAnswer?.trim()
      ? { expected_answer: item.expectedAnswer.trim() }
      : {}),
    // Deliberately NOT gated by type, unlike the two above. An MCQ's answer is
    // its bubble, so an expected answer on one is meaningless — but what a
    // bubble is WORTH is not, and a written item becomes auto-gradeable the
    // moment a vision verdict lands.
    ...(item.points?.correct !== undefined ? { points_correct: item.points.correct } : {}),
    ...(item.points?.penalty !== undefined ? { points_penalty: item.points.penalty } : {}),
  };
}

export interface DraftSheet {
  items: DraftItem[];
  /** The sheet's own barème — what every item falls back to. */
  bareme: Bareme;
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
  setExpectedAnswer: (id: Uuid, value: string | undefined) => void;
  /** Change the sheet-wide barème. Items without an override follow it. */
  setBareme: (patch: Partial<Bareme>) => void;
  /** Give one item its own barème, or hand it back to the sheet's by passing
   *  `undefined` for a field. */
  setItemBareme: (id: Uuid, patch: Partial<Bareme> | undefined) => void;
  /** What the whole sheet is worth, with every override resolved. */
  totalPoints: number;
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
/**
 * Where a draft is kept between visits (F19).
 *
 * A sheet is built by reading a chapter and ticking exercises — twenty minutes
 * of choosing, held in `useState` and nowhere else. A reload, a misclicked
 * link, a phone that reclaimed the tab: gone, with no warning that it would be.
 *
 * `sessionStorage`, keyed on class and subject: a draft belongs to the pair it
 * was built for, and coming back to a different class must not hand you the
 * other one's exercises. It is per-tab, which is right — two tabs open on two
 * classes is a real thing a teacher does in a free period.
 */
const DRAFT_PREFIX = 'alppy.draft.';

interface StoredDraft {
  items: DraftItem[];
  bareme: Bareme;
}

function readDraft(key: string | null): StoredDraft | null {
  if (!key) return null;
  try {
    const raw = window.sessionStorage.getItem(DRAFT_PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredDraft>;
    // A stored shape is a shape from an older build. Anything that is not what
    // this version expects is dropped rather than rendered: a half-understood
    // draft is worse than an empty one, because the teacher would print it.
    if (!Array.isArray(parsed.items)) return null;
    if (!parsed.items.every((item) => item?.exercise?.id)) return null;
    return {
      items: parsed.items,
      bareme:
        parsed.bareme && typeof parsed.bareme.correct === 'number'
          ? parsed.bareme
          : { correct: DEFAULT_POINTS_CORRECT, penalty: DEFAULT_POINTS_PENALTY },
    };
  } catch {
    return null;
  }
}

export function useDraftSheet(scopeKey: string | null = null): DraftSheet {
  const [items, setItems] = useState<DraftItem[]>([]);
  const [bareme, setBaremeState] = useState<Bareme>({
    correct: DEFAULT_POINTS_CORRECT,
    penalty: DEFAULT_POINTS_PENALTY,
  });

  // Restored after mount, never during render: `sessionStorage` does not exist
  // on the server, and reading it while rendering would make the two disagree.
  useEffect(() => {
    const stored = readDraft(scopeKey);
    setItems(stored?.items ?? []);
    if (stored?.bareme) setBaremeState(stored.bareme);
  }, [scopeKey]);

  useEffect(() => {
    if (!scopeKey) return;
    try {
      // An empty draft is removed rather than stored: leaving `{items: []}`
      // behind would make "nothing here" indistinguishable from "never
      // started", and the beforeunload guard below reads the same emptiness.
      if (items.length === 0) window.sessionStorage.removeItem(DRAFT_PREFIX + scopeKey);
      else
        window.sessionStorage.setItem(
          DRAFT_PREFIX + scopeKey,
          JSON.stringify({ items, bareme } satisfies StoredDraft),
        );
    } catch {
      /* Full, or blocked. A lost draft is bad; a screen that will not render
         because it could not save one is worse. */
    }
  }, [scopeKey, items, bareme]);

  // The browser's own warning, which is the only one that can interrupt a
  // navigation the app never sees — closing the tab, or the back button.
  useEffect(() => {
    if (items.length === 0) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [items.length]);

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
              ...(item.expectedAnswer !== undefined ? { expectedAnswer: item.expectedAnswer } : {}),
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

  const setExpectedAnswer = useCallback((id: Uuid, value: string | undefined) => {
    setItems((current) =>
      current.map((item) => {
        if (item.exercise.id !== id) return item;
        const { expectedAnswer: _dropped, ...rest } = item;
        return value === undefined ? rest : { ...rest, expectedAnswer: value };
      }),
    );
  }, []);

  const setBareme = useCallback((patch: Partial<Bareme>) => {
    setBaremeState((current) => ({ ...current, ...patch }));
  }, []);

  const setItemBareme = useCallback((id: Uuid, patch: Partial<Bareme> | undefined) => {
    setItems((current) =>
      current.map((item) => {
        if (item.exercise.id !== id) return item;
        if (patch === undefined) {
          // Back to following the sheet. The key is dropped rather than set to
          // the sheet's current values, so a later change to the sheet's
          // barème still moves this item.
          const { points: _dropped, ...rest } = item;
          return rest;
        }
        const next = { ...item.points, ...patch };
        const cleaned = Object.fromEntries(
          Object.entries(next).filter(([, v]) => v !== undefined),
        ) as Partial<Bareme>;
        return Object.keys(cleaned).length === 0
          ? (({ points: _dropped, ...rest }) => rest)(item)
          : { ...item, points: cleaned };
      }),
    );
  }, []);

  const totalPoints = useMemo(
    () => items.reduce((sum, item) => sum + baremeOf(item, bareme).correct, 0),
    [items, bareme],
  );

  const clear = useCallback(() => {
    setItems([]);
    // The persisted copy goes with it: `clear` is called on a successful
    // creation, and a draft that outlived the sheet it became would be offered
    // back the next time this class's builder opened.
    try {
      if (scopeKey) window.sessionStorage.removeItem(DRAFT_PREFIX + scopeKey);
    } catch {
      /* nothing to clean up if there was nowhere to write */
    }
  }, [scopeKey]);

  return {
    items,
    bareme,
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
    setExpectedAnswer,
    setBareme,
    setItemBareme,
    totalPoints,
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
