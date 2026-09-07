'use client';

import {
  Badge,
  Button,
  IconBook,
  IconCheck,
  IconChevronDown,
  IconPlus,
  LoadingState,
  Modal,
  Panel,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useExtractSection, useJob, useSourceSections } from '@/lib/api/queries';
import type { SourceSectionOut, Uuid } from '@/lib/api/types';

interface Props {
  sourceId: Uuid | null;
  section: SourceSectionOut | null;
  onSelect: (section: SourceSectionOut) => void;
}

/**
 * The book's own table of contents, and the door to the rest of it.
 *
 * A textbook is not a list to scroll — it is a structure to navigate, and the
 * teacher already knows which chapter they are teaching. This is therefore the
 * builder's only filter on *where* an exercise comes from; the curriculum theme
 * the model inferred is not a second one, because the chapter already says it.
 *
 * It is also where on-demand extraction surfaces. Importing a 400-page book
 * maps every chapter and indexes every page, but transcribes only as many
 * chapters as the import budget allows; the rest carry `extracted_at: null` and
 * are read here, when somebody actually wants them.
 */
export function SectionPicker({ sourceId, section, onSelect }: Props) {
  const t = useTranslations('builder');
  const tc = useTranslations('common');
  const [open, setOpen] = useState(false);

  const sections = useSourceSections(sourceId);
  const extract = useExtractSection();
  const [jobId, setJobId] = useState<Uuid | null>(null);
  const [extractingId, setExtractingId] = useState<Uuid | null>(null);
  const job = useJob(jobId);

  // The rows only exist once the worker finishes, so the chapter cannot be
  // opened until then — showing it empty would read as "this chapter has none".
  const status = job.data?.status;
  const refetchSections = sections.refetch;
  useEffect(() => {
    if (status !== 'succeeded' && status !== 'failed') return;
    setJobId(null);
    setExtractingId(null);
    // The rows only exist once the worker has written them, so the outline is
    // stale exactly here and nowhere earlier.
    void refetchSections();
  }, [status, refetchSections]);

  function onExtract(target: SourceSectionOut) {
    if (!sourceId) return;
    setExtractingId(target.id);
    extract.mutate(
      { sourceId, sectionId: target.id },
      {
        onSuccess: (started) => setJobId(started.id),
        onError: () => setExtractingId(null),
      },
    );
  }

  if (!sourceId) return null;

  return (
    <>
      <Panel sunken className="flex items-center gap-3">
        <IconBook size={20} className="shrink-0 text-primary-700" aria-hidden />
        <div className="min-w-0 flex-grow">
          {section ? (
            <>
              <p className="truncate font-display font-semibold">
                {section.label ? `${section.label} · ` : ''}
                {section.title}
              </p>
              <p className="text-body-s text-ink-500">
                {t('chapterPages', { from: section.page_from, to: section.page_to })} ·{' '}
                {t('exerciseCount', { count: section.exercise_count })}
              </p>
            </>
          ) : (
            <p className="text-body-s text-ink-500">{t('documentPlaceholder')}</p>
          )}
        </div>
        <Button
          variant="secondary"
          size="sm"
          trailingIcon={<IconChevronDown />}
          onClick={() => setOpen(true)}
        >
          {t('changeChapter')}
        </Button>
      </Panel>

      <Modal
        open={open}
        onOpenChange={setOpen}
        title={t('chapter')}
        description={t('extractHelp')}
        closeLabel={tc('close')}
        size="lg"
      >
        {sections.isPending ? (
          <LoadingState shape="list" label={tc('loading')} rows={5} />
        ) : (
          <ul className="flex list-none flex-col gap-2 p-0">
            {(sections.data ?? []).map((row) => {
              const isCurrent = row.id === section?.id;
              const isExtracting = extractingId === row.id;
              const isExtracted = row.extracted_at !== null;
              // A chapter read from the page layout has its exercises before
              // any model has classified them. It opens like any other; the
              // model pass stays available as a secondary action.
              const hasRows = row.exercise_count > 0;
              const canOpen = isExtracted || hasRows;
              return (
                <li key={row.id}>
                  <Panel
                    className={isCurrent ? 'border-primary-500 bg-primary-050' : undefined}
                    sunken={!canOpen && !isCurrent}
                  >
                    <div className="flex flex-wrap items-center gap-3">
                      <span
                        className="mono w-6 shrink-0 font-display font-bold text-ink-500"
                        data-numeric
                      >
                        {row.label ?? '—'}
                      </span>
                      <div className="min-w-0 flex-grow">
                        <p className="font-display font-semibold">{row.title}</p>
                        <p className="text-body-s text-ink-500">
                          {t('chapterPages', { from: row.page_from, to: row.page_to })}
                          {isExtracted ? '' : ` · ${t(hasRows ? 'notTagged' : 'notExtracted')}`}
                        </p>
                      </div>

                      {isExtracting ? (
                        <Badge variant="info">{t('extracting')}</Badge>
                      ) : canOpen ? (
                        <>
                          {/* Green would say "we have these" over the words
                              "no exercises". A chapter that was read and held
                              nothing is a real state, and it is neutral. */}
                          <Badge
                            variant={
                              row.exercise_count === 0
                                ? 'neutral'
                                : isCurrent
                                  ? 'primary'
                                  : 'success'
                            }
                          >
                            {t('exerciseCount', { count: row.exercise_count })}
                          </Badge>
                          {isCurrent ? (
                            <IconCheck size={20} className="text-primary-500" aria-hidden />
                          ) : (
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => {
                                onSelect(row);
                                setOpen(false);
                              }}
                            >
                              {t('openChapter')}
                            </Button>
                          )}
                          {isExtracted ? null : (
                            <Button
                              size="sm"
                              variant="ghost"
                              leadingIcon={<IconPlus />}
                              onClick={() => onExtract(row)}
                            >
                              {t('tagChapter')}
                            </Button>
                          )}
                        </>
                      ) : (
                        <Button
                          size="sm"
                          variant="secondary"
                          leadingIcon={<IconPlus />}
                          onClick={() => onExtract(row)}
                        >
                          {t('extract')}
                        </Button>
                      )}
                    </div>

                    {isExtracting && job.data ? (
                      <div className="mt-3 flex flex-col gap-1.5">
                        <div
                          className="h-2 overflow-hidden rounded-pill border border-line bg-surface-2"
                          role="progressbar"
                          aria-valuenow={Math.round((job.data.progress ?? 0) * 100)}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-label={t('extracting')}
                        >
                          <div
                            className="h-full bg-info-500"
                            style={{ width: `${Math.round((job.data.progress ?? 0) * 100)}%` }}
                          />
                        </div>
                        {job.data.message ? (
                          <p className="text-body-s text-ink-500">{job.data.message}</p>
                        ) : null}
                      </div>
                    ) : null}

                    {row.extraction_notice ? (
                      <p className="mt-2 text-body-s text-warn-600" role="status">
                        {row.extraction_notice}
                      </p>
                    ) : null}
                  </Panel>
                </li>
              );
            })}
          </ul>
        )}

        {extract.isError ? (
          <p className="mt-3 text-body-s text-danger-600" role="alert">
            {t('extractFailed')}
          </p>
        ) : null}
      </Modal>
    </>
  );
}
