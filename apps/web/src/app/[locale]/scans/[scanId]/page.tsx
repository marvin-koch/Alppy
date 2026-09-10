'use client';

import {
  AiBadge,
  Badge,
  Breadcrumb,
  Button,
  Card,
  Checkbox,
  ConfidenceBar,
  EmptyState,
  ErrorState,
  Field,
  IlloTray,
  KeyboardHint,
  LoadingState,
  Panel,
  ProgressRing,
  ScanReviewOverlay,
  SegmentedControl,
  Select,
  Spinner,
  type ScanMark,
  type ScanMarkState,
} from '@alppy/ui';
import { SCAN_THRESHOLDS, SHEET_LAYOUT } from '@alppy/shared';
import { useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { use, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  useAssignScanPage,
  useConfirmScan,
  useCorrectDetection,
  useReopenScan,
  useDiscardScanPage,
  useJob,
  useScan,
  useScanStudents,
  useSheet,
} from '@/lib/api/queries';
import { Link } from '@/i18n/navigation';
import { apiErrorMessage } from '@/lib/api/error-message';
import type { DetectionCorrection, DetectionOut, ScanPageOut, Uuid } from '@/lib/api/types';
import { OpenAnswerCard } from '@/components/OpenAnswerCard';
import { badgeVariant } from '@/lib/detectionOutcome';
import { useFormatters } from '@/lib/format';
import { studentName } from '@/lib/studentName';

/**
 * Below this the pipeline stops trusting itself and the item goes to the top of
 * the queue. Generated from `alppy.scan.detector`, not typed here: the review
 * screen must draw the same line the detector draws, and a copy of the number
 * three files and one language away from the original is a copy that drifts.
 */
const LOW_CONFIDENCE = SCAN_THRESHOLDS.lowConfidence;

/**
 * Where the four fiducials sit inside a registered page, as fractions of it.
 *
 * The detector reports bubble positions relative to the frame those fiducials
 * span, and the frame is not the page: on A4 it runs 18–192 mm across a 210 mm
 * sheet. Taking one for the other puts every box one to two bubble pitches out.
 */
const FRAME = {
  u: SHEET_LAYOUT.frame.x0Mm / SHEET_LAYOUT.pageWMm,
  v: SHEET_LAYOUT.frame.y0Mm / SHEET_LAYOUT.pageHMm,
  w: SHEET_LAYOUT.frame.wMm / SHEET_LAYOUT.pageWMm,
  h: SHEET_LAYOUT.frame.hMm / SHEET_LAYOUT.pageHMm,
};

/** The outcomes worth filtering to. Everything else is settled work. */
const FILTER_OUTCOMES = ['low_confidence', 'multiple', 'corrected', 'pending'] as const;
type FilterOutcome = (typeof FILTER_OUTCOMES)[number];

function isFilterOutcome(outcome: string): outcome is FilterOutcome {
  return (FILTER_OUTCOMES as readonly string[]).includes(outcome);
}

/** Pages of one student are one physical copy; an unassigned page is its own,
 *  keyed by page id so it still gets a row in the picker. */
function copyKey(page: { student_id: string | null; id: string }): string {
  return page.student_id ?? `page:${page.id}`;
}

export default function ScanReviewPage({ params }: { params: Promise<{ scanId: string }> }) {
  const { scanId } = use(params);
  const t = useTranslations('scans');
  const fmt = useFormatters();
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const tErr = useTranslations('errors.code');
  const tnav = useTranslations('nav');
  const a11y = useTranslations('a11y');

  // The worker reports "page 15 of 28" on the job it was given; the upload
  // screen passes that job through so the teacher can watch it rather than
  // stare at a screen that looks finished and empty.
  const jobId = useSearchParams().get('job');
  const scan = useScan(scanId);
  // The sheet the pile was printed from, for the breadcrumb and nothing else.
  const sheet = useSheet(scan.data?.sheet_id ?? null);
  const job = useJob(jobId);
  const students = useScanStudents(scanId);
  const correct = useCorrectDetection(scanId);
  const confirm = useConfirmScan(scanId);
  const reopen = useReopenScan(scanId);
  const [selected, setSelected] = useState<Uuid | null>(null);
  const rowRefs = useRef(new Map<Uuid, HTMLLIElement>());

  const status = scan.data?.status;
  const processing = status === 'uploaded' || status === 'processing';

  // Low confidence first: the whole point of the review screen is that the
  // teacher's attention goes where the machine is least sure, not top to bottom.
  const pages = useMemo(
    () =>
      (scan.data?.pages ?? []).map((page) => ({
        ...page,
        detections: [...page.detections].sort((a, b) => queueRank(a) - queueRank(b)),
      })),
    [scan.data],
  );

  // --- filters. A VIEW concern, and only a view concern. -------------------
  const [outcomeFilter, setOutcomeFilter] = useState<Set<FilterOutcome>>(
    () => new Set<FilterOutcome>(),
  );
  const [copyFilter, setCopyFilter] = useState('');
  const filtered = outcomeFilter.size > 0 || copyFilter !== '';

  const outcomeCounts = useMemo(() => {
    const counts: Record<FilterOutcome, number> = {
      low_confidence: 0,
      multiple: 0,
      corrected: 0,
      pending: 0,
    };
    for (const page of pages) {
      for (const d of page.detections) {
        if (isFilterOutcome(d.outcome)) counts[d.outcome] += 1;
      }
    }
    return counts;
  }, [pages]);

  const copies = useMemo(() => {
    const byKey = new Map<string, { key: string; label: string; unsure: number }>();
    for (const page of pages) {
      const key = copyKey(page);
      const entry = byKey.get(key) ?? {
        key,
        label: page.detected_uid ?? t('unidentifiedCopy'),
        unsure: 0,
      };
      entry.unsure += page.detections.filter(needsAHuman).length;
      byKey.set(key, entry);
    }
    return [...byKey.values()];
  }, [pages, t]);

  const visiblePages = useMemo(
    () =>
      pages
        .filter((page) => copyFilter === '' || copyKey(page) === copyFilter)
        .map((page) => ({
          ...page,
          detections:
            outcomeFilter.size === 0
              ? page.detections
              : page.detections.filter(
                  (d) => isFilterOutcome(d.outcome) && outcomeFilter.has(d.outcome),
                ),
        }))
        // A page with nothing left to show still appears when it is the page
        // ITSELF that needs attention.
        .filter(
          (page) =>
            page.detections.length > 0 ||
            page.wrong_class ||
            !page.registered ||
            page.discarded,
        ),
    [pages, outcomeFilter, copyFilter],
  );

  // The queue follows the filter — narrowing the view should narrow what N
  // walks through, which is the useful behaviour.
  const queue = useMemo(
    () => visiblePages.flatMap((p) => p.detections).filter(needsAHuman),
    [visiblePages],
  );
  // Written answers still with the grader. Confirming now would lock the
  // pile with those answers unrecorded, and there is no second confirmation.
  //
  // Deliberately counted over the UNFILTERED pages: a filter is a way of
  // looking, never a way of signing off. Hiding a pending answer must not make
  // Confirm available while it is still unread.
  const reading = useMemo(
    () => pages.flatMap((p) => p.detections).filter((d) => d.outcome === 'pending').length,
    [pages],
  );

  /** Move to the next item the machine was unsure about, and focus it. */
  const goToNext = useCallback(() => {
    if (queue.length === 0) return;
    const at = queue.findIndex((d) => d.id === selected);
    const next = queue[(at + 1) % queue.length];
    if (!next) return;
    setSelected(next.id);
    const row = rowRefs.current.get(next.id);
    row?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    row?.querySelector<HTMLElement>('button, [role="radio"]')?.focus();
  }, [queue, selected]);

  // "N" for the next uncertain item. Reviewing a 28-page pile means hundreds of
  // Tab presses otherwise, and the machine already knows which items are worth
  // the teacher's attention.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== 'n' && event.key !== 'N') return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      // Never steal a keystroke someone is typing into a field.
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return;
      event.preventDefault();
      goToNext();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [goToNext]);

  if (scan.isLoading) return <LoadingState shape="list" label={tc('loading')} rows={6} />;
  if (scan.isError || !scan.data) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={<Button onClick={() => void scan.refetch()}>{tc('retry')}</Button>}
      />
    );
  }

  if (scan.data.status === 'failed') {
    return (
      <ErrorState
        title={t('failed.title')}
        description={scan.data.error ?? t('failed.body')}
        action={<Button onClick={() => void scan.refetch()}>{tc('retry')}</Button>}
      />
    );
  }

  const confirmed = scan.data.status === 'confirmed';
  // Driven by the job, not by its prose: `message` is a log line, in English.
  const progress = job.data?.progress ?? 0;
  const queued = (job.data?.status ?? 'queued') === 'queued';
  // The lifecycle a teacher reads, derived rather than stored: `status` still
  // answers only "is this pile signed off?" (D48).
  const stage = processing
    ? 'processing'
    : confirmed
      ? scan.data.revised
        ? 'revised'
        : 'validated'
      : scan.data.reopened_at
        ? 'reopened'
        : 'pending';

  return (
    <div className="mx-auto max-w-5xl">
      {/* The pile came from a sheet, and "which paper is this?" is the first
          thing a teacher asks halfway through a correction session. */}
      <Breadcrumb
        className="mb-2"
        label={a11y('breadcrumb')}
        items={[
          { label: tnav('scans'), href: '/scans', key: 'scans' },
          ...(sheet.data
            ? [
                {
                  label: sheet.data.title,
                  href: `/sheets/${sheet.data.id}`,
                  key: 'sheet',
                },
              ]
            : []),
          { label: t('review'), key: 'review' },
        ]}
        renderLink={(item, children) => <Link href={item.href!}>{children}</Link>}
      />
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1>{t('review')}</h1>
            {/* Colour AND a word: the stage is never signalled by tint alone. */}
            <Badge variant={processing ? 'info' : confirmed ? 'success' : 'warn'}>
              {t(`stage.${stage}`)}
            </Badge>
          </div>
          <p className="text-body-s text-ink-500">{t('reviewHelp')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {queue.length > 0 && !confirmed ? (
            <Button variant="secondary" onClick={goToNext}>
              {t('nextToCheck')}
              <KeyboardHint keys={['N']} />
            </Button>
          ) : null}
          {confirmed ? (
            <Button
              variant="secondary"
              loading={reopen.isPending}
              busyLabel={t('reopening')}
              onClick={() => reopen.mutate()}
            >
              {t('reopen')}
            </Button>
          ) : (
            <Button
              variant="primary"
              loading={confirm.isPending}
              busyLabel={t('confirming')}
              onClick={() => confirm.mutate()}
              disabled={processing || reading > 0}
            >
              {t('confirm')}
            </Button>
          )}
        </div>
      </header>

      {processing ? (
        // A scan still being read must not look like a finished empty one —
        // and must not look failed either. Two things were wrong here: a ring
        // drawn at 0 (a meter reporting "no progress", when in truth nobody
        // has started measuring yet), and the job's own `message`, which is
        // English developer text written for a log and was being shown to a
        // teacher. The stage drives the words now; the server string never
        // reaches the screen.
        <Panel className="mb-4 flex items-center gap-4" role="status" aria-live="polite">
          {progress > 0 ? (
            <ProgressRing
              value={progress}
              centre={fmt.percent(progress)}
              label={t('processingLabel')}
              size={56}
            />
          ) : (
            <Spinner size={32} className="shrink-0 text-primary-600" />
          )}
          <div className="min-w-0">
            {/* The ring states the number; the words say what is happening.
                Saying "42" in both was two answers to one question. */}
            <p className="text-body font-bold text-ink-900">
              {t(queued ? 'processingQueued' : 'processingReading')}
            </p>
            <p className="text-body-s text-ink-500">{t('processingHelp')}</p>
          </div>
        </Panel>
      ) : (
        <Panel className="mb-4" role={reading > 0 ? 'status' : undefined}>
          <p className="text-body-s">{t('itemsToCheck', { count: queue.length })}</p>
          {reading > 0 ? (
            <p className="mt-1 flex items-center gap-3 text-body-s text-ink-700">
              <Spinner size={20} className="shrink-0 text-primary-600" />
              {t('readingAnswers', { count: reading })}
            </p>
          ) : null}
        </Panel>
      )}

      {confirm.isSuccess ? (
        <Panel className="mb-4" role="status">
          <p className="text-body-s">
            {t('confirmedCount', {
              attempts: confirm.data.attempts_created + confirm.data.attempts_superseded,
              students: confirm.data.students_affected,
            })}
          </p>
          {confirm.data.items_skipped > 0 ? (
            // Not a zero, and not silence either: an item that went in on paper
            // and comes out of the pipeline with no record is worth saying.
            <p className="mt-1 text-body-s text-warn-600">
              {t('itemsSkipped', { count: confirm.data.items_skipped })}
            </p>
          ) : null}
        </Panel>
      ) : null}

      {confirm.isError ? (
        <Panel className="mb-4" role="alert">
          <p className="text-body-s text-danger-600">{apiErrorMessage(confirm.error, tErr)}</p>
        </Panel>
      ) : null}

      {!processing && pages.length === 0 ? (
        <EmptyState
          illustration={<IlloTray />}
          title={t('empty.title')}
          description={t('empty.body')}
          size="sm"
        />
      ) : null}

      {!processing && pages.length > 0 ? (
        <Card className="mb-4 flex flex-wrap items-end gap-4" data-scan-filters>
          <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
            <legend className="text-label uppercase text-ink-500">{t('filterOutcome')}</legend>
            <div className="flex flex-wrap gap-3">
              {FILTER_OUTCOMES.map((outcome) => (
                <Checkbox
                  key={outcome}
                  label={`${t(`outcome.${outcome}`)} (${outcomeCounts[outcome]})`}
                  checked={outcomeFilter.has(outcome)}
                  onChange={() =>
                    setOutcomeFilter((current) => {
                      const next = new Set(current);
                      if (next.has(outcome)) next.delete(outcome);
                      else next.add(outcome);
                      return next;
                    })
                  }
                />
              ))}
            </div>
          </fieldset>
          <Field label={t('filterCopy')}>
            <Select value={copyFilter} onChange={(e) => setCopyFilter(e.currentTarget.value)}>
              <option value="">{t('filterAllCopies')}</option>
              {copies.map((copy) => (
                <option key={copy.key} value={copy.key}>
                  {copy.unsure > 0
                    ? t('filterCopyUnsure', { uid: copy.label, count: copy.unsure })
                    : copy.label}
                </option>
              ))}
            </Select>
          </Field>
          {filtered ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setOutcomeFilter(new Set());
                setCopyFilter('');
              }}
            >
              {t('filterClear')}
            </Button>
          ) : null}
        </Card>
      ) : null}

      {!processing && pages.length > 0 && visiblePages.length === 0 ? (
        <EmptyState
          title={t('filterNoMatches')}
          size="sm"
          action={
            <Button
              onClick={() => {
                setOutcomeFilter(new Set());
                setCopyFilter('');
              }}
            >
              {t('filterClear')}
            </Button>
          }
        />
      ) : null}

      <div className="flex flex-col gap-4">
        {visiblePages.map((page) => (
          <PageCard
            key={page.id}
            scanId={scanId}
            page={page}
            confirmed={confirmed}
            selected={selected}
            onSelect={setSelected}
            registerRow={(id, el) => {
              if (el) rowRefs.current.set(id, el);
              else rowRefs.current.delete(id);
            }}
            onCorrect={(detectionId, body) => correct.mutate({ detectionId, body })}
            students={students.data ?? []}
          />
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ page --- */

function PageCard({
  scanId,
  page,
  confirmed,
  selected,
  onSelect,
  onCorrect,
  registerRow,
  students,
}: {
  scanId: Uuid;
  page: ScanPageOut;
  confirmed: boolean;
  selected: Uuid | null;
  onSelect: (id: Uuid) => void;
  onCorrect: (detectionId: Uuid, body: DetectionCorrection) => void;
  registerRow: (id: Uuid, el: HTMLLIElement | null) => void;
  students: { id: Uuid; uid: string; first_name: string | null; last_name: string | null }[];
}) {
  const t = useTranslations('scans');
  const tc = useTranslations('common');
  const assign = useAssignScanPage(scanId);
  const discard = useDiscardScanPage(scanId);
  const [choice, setChoice] = useState<Uuid | ''>('');

  const marks = useMemo(() => toScanMarks(page.detections), [page.detections]);

  return (
    <Card data-discarded={page.discarded ? 'true' : undefined}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="min-w-0 break-words text-h3">
          {page.detected_uid ? (
            t('identifiedAs', { uid: page.detected_uid })
          ) : (
            <span className="text-danger-600">{t('notIdentified')}</span>
          )}
        </h2>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {page.wrong_class ? <Badge variant="warn">{t('wrongClass')}</Badge> : null}
          {page.discarded ? <Badge variant="neutral">{t('discarded')}</Badge> : null}
          {!page.registered ? <Badge variant="danger">{t('registrationFailed')}</Badge> : null}
          {!confirmed ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => discard.mutate({ pageId: page.id, discarded: !page.discarded })}
            >
              {page.discarded ? t('restore') : t('discard')}
            </Button>
          ) : null}
        </div>
      </div>

      {page.wrong_class ? (
        <p className="mb-3 text-body-s text-ink-700">{t('wrongClassHelp')}</p>
      ) : null}

      {!page.registered ? (
        <>
          <p className="text-body-s text-ink-700">{t('registrationWhy')}</p>
          <p className="text-body-s text-ink-700">{t('registrationHelp')}</p>
          {page.registration_error ? (
            <p className="mt-1 text-body-s text-ink-500">{page.registration_error}</p>
          ) : null}
        </>
      ) : null}

      {/* A page whose printed code could not be read is the one case the
          pipeline hands back to the teacher by design. Handing it back with no
          control to resolve it is what left a whole pile unconfirmable. */}
      {page.registered && !page.student_id && !page.discarded && !confirmed ? (
        <Panel className="mb-3">
          <Field label={t('assignManually')} help={t('assignHelp')}>
            <div className="flex flex-wrap items-end gap-2">
              <Select
                className="min-w-56 flex-1"
                value={choice}
                onChange={(e) => setChoice(e.target.value)}
              >
                <option value="">{t('chooseStudent')}</option>
                {students.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.uid} — {studentName(s)}
                  </option>
                ))}
              </Select>
              <Button
                variant="primary"
                disabled={!choice || assign.isPending}
                onClick={() => choice && assign.mutate({ pageId: page.id, studentId: choice })}
              >
                {tc('save')}
              </Button>
            </div>
          </Field>
        </Panel>
      ) : null}

      {page.registered && page.detections.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,9fr)]">
          {page.image_url ? (
            // The registered page, whose coordinates the boxes actually
            // describe — not the photo that came off the camera.
            <div className="lg:sticky lg:top-4 lg:self-start">
              <ScanReviewOverlay
                imageSrc={page.image_url}
                imageAlt={t('pageAlt', { page: page.page_index + 1 })}
                frame={FRAME}
                marks={marks}
                selectedId={selected ?? undefined}
                onSelectMark={(m) => onSelect(m.groupId ?? m.id)}
                regionLabel={t('marksRegion')}
                lowConfidenceThreshold={LOW_CONFIDENCE}
              />
            </div>
          ) : null}

          <ul className="flex list-none flex-col gap-3 p-0">
            {page.detections.map((d) => (
              <li key={d.id} ref={(el) => registerRow(d.id, el)}>
                {d.exercise_type === 'open' ? (
                  // A written answer: the box, what was read in it, and a
                  // verdict to confirm or overrule. No bubbles to pick from.
                  <OpenAnswerCard
                    detection={d}
                    selected={selected === d.id}
                    readOnly={confirmed || page.discarded}
                    lowConfidence={LOW_CONFIDENCE}
                    onSelect={() => onSelect(d.id)}
                    onCorrect={(body) => onCorrect(d.id, body)}
                  />
                ) : (
                  <DetectionRow
                    detection={d}
                    selected={selected === d.id}
                    readOnly={confirmed || page.discarded}
                    onSelect={() => onSelect(d.id)}
                    onCorrect={(index) => onCorrect(d.id, { detected_index: index })}
                  />
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}

/* ------------------------------------------------------------------- row --- */

function DetectionRow({
  detection,
  selected,
  readOnly,
  onSelect,
  onCorrect,
}: {
  detection: DetectionOut;
  selected: boolean;
  readOnly: boolean;
  onSelect: () => void;
  onCorrect: (index: number | null) => void;
}) {
  const t = useTranslations('scans');
  // The glyphs the student saw on the paper: ABCD for an MCQ, V/F, R/F or T/F
  // for a true/false item. Labelling a true/false override "A / B" asks the
  // teacher to remember that bubble 0 means true.
  const letters = detection.option_letters ?? 'ABCD';
  const count = detection.fill_ratios?.length ?? letters.length;

  return (
    <Panel
      sunken={needsAHuman(detection)}
      onClick={onSelect}
      className={selected ? 'shadow-[var(--focus-ring)]' : undefined}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="mono text-body-s" data-numeric>
          #{detection.number ?? detection.item_index + 1}
        </span>
        <div className="flex items-center gap-2">
          {detection.ai_generated ? <AiBadge label={t('aiGenerated')} size="sm" /> : null}
          <Badge variant={badgeVariant(detection.outcome)}>
            {t(`outcome.${detection.outcome}`)}
          </Badge>
        </div>
      </div>

      {/* What was asked. Adjudicating "#7, low confidence, A/B/C/D" against
          nothing is not something a teacher can do. */}
      {detection.statement ? (
        <p className="mt-2 text-body-s text-ink-900">{detection.statement}</p>
      ) : null}
      {detection.options?.length ? (
        <ol className="mt-1 list-none p-0 text-body-s text-ink-700">
          {detection.options.map((option, i) => (
            <li key={option}>
              <span className="font-bold">{letters[i] ?? i}</span> · {option}
              {/* Which one was right. Never colour alone: the word carries it. */}
              {i === detection.answer_index ? (
                <span className="ml-2 text-body-s font-bold text-success-600">
                  {t('isTheAnswer')}
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      ) : detection.answer_index !== null && detection.option_letters ? (
        <p className="mt-1 text-body-s text-ink-700">
          {t('answerIs', { answer: letters[detection.answer_index] ?? '' })}
        </p>
      ) : null}

      <div className="mt-2">
        <ConfidenceBar
          value={detection.confidence}
          threshold={LOW_CONFIDENCE}
          label={t('confidence')}
          lowLabel={t('lowConfidence')}
        />
      </div>

      {/* The machine's reading is kept beside the override, not under it. */}
      {detection.corrected_at && detection.machine_outcome ? (
        <p className="mt-2 text-body-s text-ink-500">
          {t('machineRead', {
            answer:
              detection.machine_index === null
                ? '—'
                : (letters[detection.machine_index] ?? String(detection.machine_index)),
            outcome: t(`outcome.${detection.machine_outcome}`),
          })}
        </p>
      ) : null}

      {detection.outcome !== 'not_gradeable' && !readOnly ? (
        <div className="mt-3">
          {/* One click corrects the machine. Always available, never buried.
              size="md" and block: 44px touch targets, which the sm variant
              cannot give on a 390px screen. */}
          <SegmentedControl
            value={String(detection.detected_index ?? '')}
            onValueChange={(v) => onCorrect(v === '' ? null : Number(v))}
            label={t('detected')}
            block
            options={[
              ...Array.from({ length: count }, (_, i) => ({
                value: String(i),
                label: letters[i] ?? String(i),
              })),
              { value: '', label: '—' },
            ]}
          />
        </div>
      ) : null}
    </Panel>
  );
}

/* ----------------------------------------------------------------- utils --- */

/** An item the teacher has to look at before anything is written down. */
function needsAHuman(d: DetectionOut): boolean {
  if (d.outcome === 'not_gradeable' || d.outcome === 'corrected') return false;
  // Pending is the grader's, not the teacher's — nothing to check yet.
  if (d.outcome === 'pending') return false;
  return d.outcome === 'multiple' || d.confidence < LOW_CONFIDENCE;
}

/**
 * Queue order. Confidence alone is not monotonic across outcomes — `multiple`
 * peaks at 0.5 when the two fills are equal — so ambiguity sorts first on its
 * own terms, then the least confident reading, and settled items go last.
 */
function queueRank(d: DetectionOut): number {
  if (d.outcome === 'multiple') return -1;
  if (d.outcome === 'corrected' || d.outcome === 'not_gradeable') return 2;
  if (d.outcome === 'pending') return 1.5;
  return d.confidence;
}

/**
 * Detections -> overlay boxes.
 *
 * `bubble_boxes` is typed as `Record<string, number>[]` because the schema does
 * not name its keys, so read them defensively rather than assuming.
 */
function toScanMarks(detections: DetectionOut[]): ScanMark[] {
  const marks: ScanMark[] = [];
  for (const d of detections) {
    const boxes = d.bubble_boxes ?? [];
    const chosen = d.detected_index;
    for (const [index, box] of boxes.entries()) {
      const { u, v, w, h } = box;
      if ([u, v, w, h].some((n) => typeof n !== 'number')) continue;
      // Only the bubble the pipeline settled on carries the item's state; the
      // others are drawn as the empty positions they are.
      const isChosen = index === chosen;
      marks.push({
        id: `${d.id}:${index}`,
        groupId: d.id,
        u,
        v,
        w,
        h,
        state: isChosen ? markState(d) : 'empty',
        confidence: isChosen ? d.confidence : 1,
        label: `#${d.number ?? d.item_index + 1} · ${(d.option_letters ?? 'ABCD')[index] ?? index}`,
      });
    }
  }
  return marks;
}

function markState(d: DetectionOut): ScanMarkState {
  if (d.outcome === 'corrected') return 'corrected';
  if (d.outcome === 'multiple' || d.confidence < LOW_CONFIDENCE) return 'ambiguous';
  if (d.detected_index === null) return 'empty';
  return 'detected';
}
