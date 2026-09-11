/**
 * Whether a sheet can be printed, and by which door.
 *
 * There used to be two ways to get paper out of Alppy and they were not
 * equivalent. **Imprimer** called `print()` on the preview iframe and then
 * recorded the sheet as printed; **Générer les PDF** ran `render_sheet` on the
 * server. Only the second writes `AnswerBoxPlacement` — the rectangles the scan
 * job crops a written answer from (`sheets/render.py`, `_persist_answer_box_placements`).
 * A sheet with open items printed through the first door came back with every
 * written answer `NOT_GRADEABLE`, counted as skipped, with nothing on the review
 * screen saying why. And even when placements existed, the paper had come off
 * the teacher's browser at the teacher's margins and the teacher's scale, while
 * the rectangles had been measured in the API's headless Chromium.
 *
 * So there is one door now: the PDF. This module is the gate on it.
 *
 * ## Why `rendered_at` is the whole answer
 *
 * It is tempting to compare timestamps — `rendered_at < updated_at` — and guess
 * at staleness on this side. Do not. The server already decides this and does it
 * authoritatively: `services/sheet_service.py:update_sheet` nulls
 * `blank_pdf_key`, `answer_key_pdf_key` **and** `rendered_at` on any edit that
 * changes the paper, including a barème edit, because every statement prints
 * what it is worth. `render.py` is the only thing that sets it again.
 *
 * So `rendered_at !== null` means exactly "the stored PDF, and the placements
 * measured from it, describe this sheet as it stands now". A client-side
 * timestamp comparison would be a second, weaker copy of a rule that already
 * exists — and the first edit that moved paper without moving `updated_at`
 * would silently disagree with it.
 */

import type { SheetOut } from './api/types';

export type PrintState =
  /** The PDF exists and was measured from this sheet. Printing it is safe. */
  | 'ready'
  /** No render, or an edit invalidated the last one. The PDF must be built. */
  | 'needs_render'
  /** A render is in flight. */
  | 'rendering';

export interface PrintReadiness {
  state: PrintState;
  /** The document to print. Null unless `state` is `ready`. */
  pdfUrl: string | null;
  /**
   * Whether this sheet has written-answer items. It does not change what the
   * gate does — a bubble-only sheet printed from a browser is still printed at
   * the browser's scale — but it is what makes the consequence concrete enough
   * to put in a sentence, so the screen can say *"and this is what would come
   * back ungraded"* rather than a rule with no stakes attached.
   */
  hasOpenItems: boolean;
}

export function printReadiness(
  sheet: SheetOut,
  options: { rendering?: boolean } = {},
): PrintReadiness {
  const hasOpenItems = sheet.items.some((item) => item.exercise.type === 'open');

  // A render in flight wins: the sheet may still carry the previous PDF, and
  // offering it while the teacher is waiting for a new one hands them the paper
  // they just decided was wrong.
  if (options.rendering) return { state: 'rendering', pdfUrl: null, hasOpenItems };

  // Both, not either. `rendered_at` is the server's verdict on whether the
  // placements are current; the url is whether there is a file to open. They
  // move together today, and if they ever stop, refusing is the safe half.
  if (sheet.rendered_at !== null && sheet.blank_pdf_url) {
    return { state: 'ready', pdfUrl: sheet.blank_pdf_url, hasOpenItems };
  }

  return { state: 'needs_render', pdfUrl: null, hasOpenItems };
}
