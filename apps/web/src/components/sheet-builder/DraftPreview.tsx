'use client';

import { Card, LoadingState } from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import { previewSheetDraft } from '@/lib/api/endpoints';
import { apiErrorMessage } from '@/lib/api/error-message';
import type { ApiLocale, Uuid } from '@/lib/api/types';
import { toSheetItemIn, type Bareme, type DraftItem } from './useDraftSheet';

interface Props {
  classId: Uuid;
  subjectId: Uuid;
  title: string;
  language: ApiLocale;
  items: DraftItem[];
  /** The sheet's barème. The preview prints what each item is worth, so it has
   *  to travel with the draft or the paper on screen disagrees with the paper
   *  that comes out of the printer. */
  bareme: Bareme;
}

/**
 * The paper, while the teacher is still choosing.
 *
 * The document is rendered by the server from the same `SheetData`, the same
 * templates and the same millimetre geometry out of `sheets/layout.py` that the
 * PDF is made from, so it cannot drift from what comes out of the printer. A
 * React re-implementation was tried once and removed: it drew the bubbles
 * inline beside each option instead of on the fixed grid the scan detector
 * reads, printed no UID grid, and hardcoded A/B/C/D where the sheet prints V/F.
 *
 * `srcdoc` rather than `src`, because the draft has no id to GET — it is posted.
 * The document is standalone (its CSS is inlined at render time), so nothing
 * needs to resolve from the frame's origin.
 */
export function DraftPreview({ classId, subjectId, title, language, items, bareme }: Props) {
  const t = useTranslations('builder');
  const tc = useTranslations('common');
  const te = useTranslations('errors');

  // A4 at 96 dpi. The page is a fixed 210 x 297 mm and the column is not, so
  // the frame is scaled to the width it actually has. Measuring beats a
  // breakpoint ladder: the preview column is one grid track among three and its
  // width does not change only at breakpoints.
  const A4_W_PX = 794;
  const A4_H_PX = 1123;
  const [scale, setScale] = useState(0.5);
  const observer = useRef<ResizeObserver | null>(null);

  // A ref *callback*, not a ref plus an effect. The measured element only
  // enters the DOM once the preview HTML has arrived, which is always after
  // this component first renders — an effect with an empty dependency array
  // therefore ran while the node was still null, attached nothing, and never
  // ran again, leaving the page pinned at the initial scale forever.
  const measure = useCallback((node: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const next = new ResizeObserver(([entry]) => {
      const width = entry?.contentRect.width ?? 0;
      if (width > 0) setScale(width / A4_W_PX);
    });
    next.observe(node);
    observer.current = next;
  }, []);

  useEffect(() => () => observer.current?.disconnect(), []);

  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // Serialised so the effect depends on the item *list*, not on an array
  // identity that changes on every render.
  const signature = JSON.stringify(
    items.map((item, index) => [item.exercise.id, index, item.override ?? null]),
  );

  useEffect(() => {
    if (items.length === 0) {
      setHtml(null);
      setError(null);
      return;
    }
    const controller = new AbortController();
    // Debounced: reordering is a burst of edits, and each one would otherwise
    // be a round trip that paginates the whole sheet.
    const timer = setTimeout(() => {
      setPending(true);
      previewSheetDraft({
        class_id: classId,
        subject_id: subjectId,
        title,
        language,
        items: items.map((item, index) => toSheetItemIn(item, index)),
        default_points_correct: bareme.correct,
        default_points_penalty: bareme.penalty,
      })
        .then((document) => {
          if (controller.signal.aborted) return;
          setHtml(document);
          setError(null);
        })
        .catch((cause: unknown) => {
          if (controller.signal.aborted) return;
          // A sheet the renderer refuses — a statement taller than a page, a
          // class with no students — answers 422 with the reason. Read it: an
          // iframe would render the raw error JSON at the teacher.
          setError(apiErrorMessage(cause, te) || t('previewFailed'));
          setHtml(null);
        })
        .finally(() => {
          if (!controller.signal.aborted) setPending(false);
        });
    }, 400);

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
    // `signature` stands in for `items` on purpose: the array identity changes
    // on every render of the parent, and re-posting the same sheet on each one
    // would make the preview flicker and hammer the pagination.
  }, [signature, classId, subjectId, title, language, items, t, te]);

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-h3">{t('preview')}</h2>
        {pending ? (
          <span className="text-body-s text-ink-500" role="status">
            {tc('loading')}
          </span>
        ) : null}
      </div>

      {error ? (
        <p className="text-body-s text-danger-600" role="alert">
          {error}
        </p>
      ) : items.length === 0 ? (
        <p className="text-body-s text-ink-500">{t('emptySheetBody')}</p>
      ) : html === null ? (
        <LoadingState shape="sheet" label={tc('loading')} />
      ) : (
        // Scaled to fit rather than scrolled sideways: the page body never
        // scrolls horizontally (plan.md §9). The wrapper takes the scaled
        // height so the card does not reserve a full A4 of empty space.
        <div
          ref={measure}
          className="w-full overflow-hidden rounded-sm border border-line bg-white"
          style={{ height: `${Math.round(A4_H_PX * scale)}px` }}
        >
          <div
            className="origin-top-left"
            style={{ transform: `scale(${scale})`, width: `${A4_W_PX}px` }}
          >
            <iframe
              srcDoc={html}
              title={t('preview')}
              className="border-0 bg-white"
              style={{ width: `${A4_W_PX}px`, height: `${A4_H_PX}px` }}
              // The document is ours and self-contained; it runs no script.
              sandbox=""
            />
          </div>
        </div>
      )}
    </Card>
  );
}
