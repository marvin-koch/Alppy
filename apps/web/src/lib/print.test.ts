/**
 * The gate on the one door to paper.
 *
 * This is the test that would have caught F1. Before it, `Imprimer` called
 * `print()` on the preview iframe and then recorded the sheet as printed —
 * paper the grading pipeline had no `AnswerBoxPlacement` rows for, and so a
 * class set of written answers that came back `NOT_GRADEABLE` with nothing
 * saying why. Nothing in the suite could see that, because the decision was
 * three lines inside a click handler and there was no decision to test.
 */

import { describe, expect, it } from 'vitest';

import type { SheetOut } from './api/types';
import { sheet as fixture } from './api/mock/fixtures';
import { printReadiness } from './print';

/** The mock sheet as the app serves it: never rendered, bubbles only. */
const unrendered: SheetOut = fixture;

/** The case F1 was about. The mock sheet has no open item — worth knowing, and
 *  asserted below — so this builds one from the fixture's own shapes. */
const withOpenItem: SheetOut = {
  ...fixture,
  items: [
    ...fixture.items,
    {
      ...fixture.items[0]!,
      id: 'open-item',
      position: fixture.items.length,
      exercise: { ...fixture.items[0]!.exercise, type: 'open', options: null },
    },
  ],
};

function rendered(over: Partial<SheetOut> = {}): SheetOut {
  return {
    ...fixture,
    rendered_at: '2026-03-14T09:00:00+01:00',
    blank_pdf_url: '/mock/blank.pdf',
    ...over,
  };
}

describe('printReadiness', () => {
  it('refuses a sheet that has never been rendered', () => {
    const state = printReadiness(unrendered);
    expect(state.state).toBe('needs_render');
    // Nothing to open: the screen cannot accidentally offer a stale document.
    expect(state.pdfUrl).toBeNull();
  });

  /** The case that used to produce a class set of ungradeable written
   *  answers: open items, no render, and — before this gate — an `Imprimer`
   *  button that printed the preview frame and recorded the print. */
  it('refuses an unrendered sheet with written answers, and knows it has them', () => {
    const state = printReadiness(withOpenItem);
    expect(state.state).toBe('needs_render');
    expect(state.hasOpenItems).toBe(true);
  });

  /** Not an assertion about the gate but about the fixtures: the mock sheet
   *  is bubbles-only, so no screen driven by it exercises an answer box. If
   *  that changes, this is the line that says the coverage changed with it. */
  it('records that the mock sheet carries no written answer', () => {
    expect(printReadiness(unrendered).hasOpenItems).toBe(false);
  });

  it('prints a sheet whose PDF was measured from it as it stands', () => {
    const state = printReadiness(rendered());
    expect(state.state).toBe('ready');
    expect(state.pdfUrl).toBe('/mock/blank.pdf');
  });

  /**
   * `update_sheet` nulls `rendered_at` on any edit that changes the paper — an
   * item list, a barème. That is the server telling us the stored placements
   * describe a sheet that no longer exists, and it is the whole staleness
   * check: the client never compares timestamps of its own.
   */
  it('refuses again once an edit has invalidated the render', () => {
    expect(printReadiness(rendered({ rendered_at: null })).state).toBe('needs_render');
  });

  /** Both halves, not either: a url with no `rendered_at` is a file whose
   *  placements we have no assurance about, and refusing is the safe half. */
  it('refuses a PDF url that no longer has a render behind it', () => {
    expect(printReadiness(rendered({ rendered_at: null, blank_pdf_url: '/old.pdf' })).state).toBe(
      'needs_render',
    );
    expect(printReadiness(rendered({ blank_pdf_url: null })).state).toBe('needs_render');
  });

  /** A render in flight offers nothing, even when a previous PDF is still on
   *  the row — that is the paper the teacher has just decided is wrong. */
  it('offers no document while a render is running', () => {
    const state = printReadiness(rendered(), { rendering: true });
    expect(state.state).toBe('rendering');
    expect(state.pdfUrl).toBeNull();
  });

  /** A bubble-only sheet goes through the same door. The reason is different —
   *  no answer boxes to miscrop, but the teacher's margins and the printer's
   *  "fit to page" are still not the geometry anything was measured against. */
  it('gates a bubble-only sheet the same way, and says so', () => {
    const state = printReadiness(unrendered);
    expect(state.hasOpenItems).toBe(false);
    expect(state.state).toBe('needs_render');
  });
});
