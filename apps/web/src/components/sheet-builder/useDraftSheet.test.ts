import { describe, expect, it } from 'vitest';

import type { ExerciseOut } from '@/lib/api/types';

import {
  ANSWER_BOX_LINES,
  answerBoxOf,
  baremeOf,
  clampAnswerBoxLines,
  DEFAULT_ANSWER_BOX_FILL,
  DEFAULT_ANSWER_BOX_LINES,
  expectedAnswerOf,
  hasOwnBareme,
  MAX_ANSWER_BOX_LINES,
  MAX_ITEM_POINTS,
  parseDecimalInput,
  toSheetItemIn,
  type DraftItem,
} from './useDraftSheet';

/**
 * The builder's own rules, which had no test file at all (T25).
 *
 * `useDraftSheet.ts` is 448 lines and is where a sheet becomes the thing the
 * API is asked to create. Everything below is a pure function with a rule in
 * it, and every rule is one where getting it wrong is quiet: a barème that
 * falls back when it should not, a zero read as "unset", a decimal comma from a
 * Swiss keyboard read as nothing.
 *
 * The hook itself (localStorage, scope keys, React state) is not covered here —
 * that wants a renderHook harness and belongs with the component tests. These
 * are the parts that decide what gets printed.
 */

const open = (over: Partial<ExerciseOut> = {}): ExerciseOut =>
  ({
    id: '00000000-0000-4000-8000-000000000001',
    type: 'open',
    origin: 'textbook',
    language: 'fr',
    statement: 'Explique ta demarche.',
    options: null,
    answer_index: null,
    answer_bool: null,
    answer_text: null,
    difficulty: 2,
    competency_ids: [],
    ...over,
  }) as ExerciseOut;

const item = (over: Partial<DraftItem> = {}): DraftItem =>
  ({ exercise: open(), ...over }) as DraftItem;

describe('parseDecimalInput', () => {
  it('reads a Swiss decimal comma as a decimal point', () => {
    // A CH-fr keyboard writes "0,5". Reading it as NaN and falling back to the
    // sheet default is a silently different barème on that item.
    expect(parseDecimalInput('0,5', 1)).toBe(0.5);
    expect(parseDecimalInput('2,25', 1)).toBe(2.25);
  });

  it('falls back on anything that is not a number', () => {
    for (const raw of ['', '   ', '-', '1.', 'abc', '..']) {
      expect(parseDecimalInput(raw, 1), `input ${JSON.stringify(raw)}`).toBe(1);
    }
  });

  it('keeps zero, which is a real choice rather than an absence', () => {
    // An item that earns nothing, or costs nothing to get wrong. If this
    // returned the fallback the teacher could not express it at all.
    expect(parseDecimalInput('0', 1)).toBe(0);
    expect(parseDecimalInput('0,0', 1)).toBe(0);
  });

  it('clamps to the range a barème may hold', () => {
    expect(parseDecimalInput('-5', 1)).toBe(0);
    expect(parseDecimalInput('999', 1)).toBe(MAX_ITEM_POINTS);
  });

  it('rounds to two places, because points are printed', () => {
    expect(parseDecimalInput('0,333', 1)).toBe(0.33);
    expect(parseDecimalInput('2,349', 1)).toBe(2.35);
  });

  it('rounds a binary-exact half down, and that is fine here', () => {
    // `Math.round(1.005 * 100)` is 100, not 101: 1.005 is not representable and
    // the product is 100.49999999999999. Recorded rather than fixed — a barème
    // is a teacher choosing 0.25, 0.5, 1, 2; nobody types a third decimal, and
    // the alternative is a string-based rounding helper carried for a case that
    // does not arise.
    expect(parseDecimalInput('1,005', 1)).toBe(1);
  });
});

describe('baremeOf', () => {
  const sheet = { correct: 2, penalty: 0.5 };

  it('falls back to the sheet when the item says nothing', () => {
    expect(baremeOf(item(), sheet)).toEqual(sheet);
  });

  it('treats an item worth ZERO as a choice, not as unset', () => {
    // The whole reason this is `?? ` against undefined rather than a truthiness
    // test — and the same rule the server applies with `is not None`. A `0 ||`
    // here hands the item the sheet's 2 points back.
    expect(baremeOf(item({ points: { correct: 0 } }), sheet).correct).toBe(0);
    expect(baremeOf(item({ points: { penalty: 0 } }), sheet).penalty).toBe(0);
  });

  it('overrides one side without disturbing the other', () => {
    expect(baremeOf(item({ points: { correct: 3 } }), sheet)).toEqual({
      correct: 3,
      penalty: 0.5,
    });
  });
});

describe('hasOwnBareme', () => {
  it('is false for an item that inherits', () => {
    expect(hasOwnBareme(item())).toBe(false);
    expect(hasOwnBareme(item({ points: {} }))).toBe(false);
  });

  it('is true for an item that chose zero', () => {
    // Same trap as above, on the control that decides whether the UI shows the
    // item as customised. An item deliberately worth 0 must not read as
    // "inherits".
    expect(hasOwnBareme(item({ points: { correct: 0 } }))).toBe(true);
    expect(hasOwnBareme(item({ points: { penalty: 0 } }))).toBe(true);
  });
});

describe('expectedAnswerOf', () => {
  it("prefers the teacher's answer over the book's", () => {
    const withBoth = item({
      expectedAnswer: 'une demi',
      exercise: open({ answer_text: '1/2' }),
    });
    expect(expectedAnswerOf(withBoth)).toBe('une demi');
  });

  it("falls back to the book's", () => {
    expect(expectedAnswerOf(item({ exercise: open({ answer_text: '1/2' }) }))).toBe('1/2');
  });

  it('is empty when neither exists, never a placeholder', () => {
    // v1 of the grader substituted a placeholder string for a missing answer
    // and then judged against the placeholder. Empty is what tells the grader
    // it has to work the answer out.
    expect(expectedAnswerOf(item())).toBe('');
  });
});

describe('answerBoxOf', () => {
  it('applies the defaults from the print layout, not from here', () => {
    expect(answerBoxOf(item())).toEqual({
      lines: DEFAULT_ANSWER_BOX_LINES,
      fill: DEFAULT_ANSWER_BOX_FILL,
    });
  });

  it("keeps the teacher's box", () => {
    expect(answerBoxOf(item({ box: { lines: 5, fill: 'grid' } }))).toEqual({
      lines: 5,
      fill: 'grid',
    });
  });
});

describe('clampAnswerBoxLines', () => {
  it('stays inside what the page geometry allows', () => {
    // `layout.py` and `print.css` describe the same geometry and the detector
    // reads it. A box taller than the page is not a display bug, it is a crop
    // that lands somewhere else.
    expect(clampAnswerBoxLines(999)).toBeLessThanOrEqual(MAX_ANSWER_BOX_LINES);
    expect(clampAnswerBoxLines(-3)).toBe(0);
  });

  it('keeps zero, because zero lines is a box the paper can print', () => {
    // 0 is the first entry in ANSWER_BOX_LINES: an open item with no ruled box
    // at all. Clamping it up to 1 would silently add a line to every item a
    // teacher had deliberately left unruled.
    expect(clampAnswerBoxLines(0)).toBe(0);
    expect(ANSWER_BOX_LINES[0]).toBe(0);
  });

  it('falls back to the default rather than propagating NaN', () => {
    expect(clampAnswerBoxLines(Number.NaN)).toBe(DEFAULT_ANSWER_BOX_LINES);
  });
});

describe('toSheetItemIn', () => {
  it('carries the position it is given, not the one it remembers', () => {
    expect(toSheetItemIn(item(), 3).position).toBe(3);
  });

  it('omits an answer box for an item that is not written', () => {
    const mcq = item({
      exercise: open({ type: 'mcq', options: ['a', 'b'], answer_index: 0 }),
      box: { lines: 4, fill: 'lined' },
    });
    const sent = toSheetItemIn(mcq, 0);
    expect(sent).not.toHaveProperty('answer_box_lines');
    expect(sent).not.toHaveProperty('expected_answer');
  });

  it('carries points for an MCQ even though it carries no expected answer', () => {
    // Deliberately not gated by type, unlike the two above: an MCQ's answer is
    // its bubble, so an expected answer on one is meaningless — but what a
    // bubble is WORTH is not.
    const mcq = item({
      exercise: open({ type: 'mcq', options: ['a', 'b'], answer_index: 0 }),
      points: { correct: 2, penalty: 0.5 },
    });
    expect(toSheetItemIn(mcq, 0)).toMatchObject({ points_correct: 2, points_penalty: 0.5 });
  });

  it('sends a zero barème rather than dropping it', () => {
    const free = item({ points: { correct: 0, penalty: 0 } });
    expect(toSheetItemIn(free, 0)).toMatchObject({ points_correct: 0, points_penalty: 0 });
  });

  it('omits a whitespace-only expected answer', () => {
    const blank = item({ expectedAnswer: '   ' });
    expect(toSheetItemIn(blank, 0)).not.toHaveProperty('expected_answer');
  });

  it('trims the expected answer it does send', () => {
    expect(toSheetItemIn(item({ expectedAnswer: '  1/2  ' }), 0)).toMatchObject({
      expected_answer: '1/2',
    });
  });
});
