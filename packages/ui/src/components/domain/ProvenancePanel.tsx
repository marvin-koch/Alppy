import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { ConfidenceBar } from './ConfidenceBar';

export interface ProvenanceLabels {
  /** "Source" / "Quelle" — the document the exercise came from. */
  source: string;
  /** "Page". */
  page: string;
  /** "Extrait" — heading for the quoted chunk. */
  excerpt: string;
  /** "Similarité" — the retrieval score. */
  similarity: string;
}

export interface ProvenancePanelProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  /** Title of the uploaded document. */
  sourceTitle: string;
  /** 1-based page in that document. */
  page?: number;
  /** The retrieved chunk, quoted verbatim. */
  excerpt: string;
  /** Retrieval similarity, 0..1. */
  similarity?: number;
  labels: ProvenanceLabels;
  /** e.g. a button opening the PDF at that page. */
  action?: ReactNode;
  /** Marks the exercise as AI-generated — pass an `<AiBadge>`. */
  aiBadge?: ReactNode;
}

/**
 * Where a proposed exercise came from (F1/F5). The teacher audits this before
 * printing, so the excerpt renders as DATA: `[data-transcription]` puts it in
 * mono (DESIGN.md §3). A panel, not a card — it is a subdivision of the
 * proposal it explains.
 */
export const ProvenancePanel = forwardRef<HTMLDivElement, ProvenancePanelProps>(function ProvenancePanel(
  { sourceTitle, page, excerpt, similarity, labels, action, aiBadge, className, ...rest },
  ref,
) {
  return (
    <div ref={ref} data-sunken="true" className={cx('ard-panel flex flex-col gap-3', className)} {...rest}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <dl className="grid min-w-0 grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-body-s">
          <dt className="type-label text-ink-500">{labels.source}</dt>
          <dd className="min-w-0 truncate font-bold text-ink-900">{sourceTitle}</dd>
          {page === undefined ? null : (
            <>
              <dt className="type-label text-ink-500">{labels.page}</dt>
              <dd data-numeric="" className="text-ink-900 tabular-nums">
                {page}
              </dd>
            </>
          )}
        </dl>
        {aiBadge}
      </div>

      <div className="flex flex-col gap-1">
        <p className="type-label text-ink-500">{labels.excerpt}</p>
        <blockquote
          data-transcription=""
          className="max-h-40 overflow-y-auto rounded-sm border-l-2 border-line-strong bg-surface px-3 py-2 text-body-s whitespace-pre-wrap"
        >
          {excerpt}
        </blockquote>
      </div>

      {similarity === undefined ? null : (
        <ConfidenceBar value={similarity} threshold={0} label={labels.similarity} size="sm" />
      )}

      {action ? <div className="flex flex-wrap gap-2">{action}</div> : null}
    </div>
  );
});
