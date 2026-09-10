'use client';

import {
  Breadcrumb,
  Chip,
  ConceptTag,
  MasteryBandTag,
  type MasteryBand,
  Button,
  Card,
  ErrorState,
  IconDownload,
  IconPrint,
  LoadingState,
  Panel,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@alppy/ui';

import { Link } from '@/i18n/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { use, useEffect, useRef, useState } from 'react';

import { ApiError, API_BASE } from '@/lib/api/client';
import { apiErrorMessage } from '@/lib/api/error-message';
import type { ApiErrorBody } from '@/lib/api/types';
import { useBandLabels } from '@/lib/bands';
import {
  useCurriculumTree,
  useJob,
  useMarkPrinted,
  useRenderSheet,
  useSheet,
  useSheetMastery,
  useSheets,
} from '@/lib/api/queries';
import { useFormatters } from '@/lib/format';

export default function SheetPage({ params }: { params: Promise<{ sheetId: string }> }) {
  const { sheetId } = use(params);
  const t = useTranslations('sheets');
  const fmt = useFormatters();
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const tnav = useTranslations('nav');
  const a11y = useTranslations('a11y');
  const tsheet = useTranslations('sheetDetail');
  const tt = useTranslations('tree');
  const tm = useTranslations('mastery');
  const locale = useLocale();
  const bandLabels = useBandLabels();

  const sheet = useSheet(sheetId);
  // The tree names the Theme and the competency codes; the sheet carries only
  // ids. One request the page was already entitled to make.
  const tree = useCurriculumTree(sheet.data?.class_id ?? null, {});
  const sheets = useSheets(sheet.data?.class_id ?? undefined);
  const mastery = useSheetMastery(sheetId);
  const render = useRenderSheet();
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const markPrinted = useMarkPrinted();

  // Which document the teacher is looking at, and the frame that holds it.
  // Print used to call `window.print()` on *this* page: the app chrome, the
  // tab strip, and the A4 preview scaled to 42 % inside a scroll box — never
  // the sheet. The preview frame is the print document itself, served with the
  // same print.css the PDF is made from, so printing means printing the frame.
  const [kind, setKind] = useState<PreviewKind>('blank');
  const frames = useRef<Record<PreviewKind, HTMLIFrameElement | null>>({
    blank: null,
    key: null,
  });

  const printPreview = () => {
    const frame = frames.current[kind];
    const target = frame?.contentWindow;
    if (target) {
      try {
        target.focus();
        target.print();
        if (kind === 'blank') markPrinted.mutate(sheetId);
        return;
      } catch {
        // A frame the browser will not let us drive falls through to a tab.
      }
    }
    // No frame (the preview errored) or a frame we cannot reach: open the
    // print document on its own so the browser's print dialog gets the sheet.
    window.open(previewUrl(sheetId, kind), '_blank', 'noopener');
  };

  // The PDF keys land on the sheet row, written by the worker — so the sheet
  // has to be re-read once the job finishes. Without this the render succeeded,
  // the files existed, and the download buttons never appeared.
  const jobStatus = job.data?.status;
  const refetchSheet = sheet.refetch;
  useEffect(() => {
    if (jobStatus === 'succeeded') void refetchSheet();
  }, [jobStatus, refetchSheet]);

  if (sheet.isLoading) return <LoadingState shape="sheet" label={tc('loading')} />;
  if (sheet.isError || !sheet.data) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={<Button onClick={() => void sheet.refetch()}>{tc('retry')}</Button>}
      />
    );
  }

  const s = sheet.data;

  const branchThemes = (tree.data?.branches ?? []).flatMap((b) =>
    b.competences.flatMap((c) => c.themes),
  );
  const homeTheme = s
    ? (() => {
        const th = branchThemes.find((x) => x.chapter_id === s.chapter_id);
        return th ? (th.labels?.[locale] ?? th.labels?.fr ?? th.key) : null;
      })()
    : null;
  const coverage = (tree.data?.branches ?? [])
    .flatMap((b) => b.competences)
    .filter((c) => s?.competency_ids.includes(c.competency_id));
  const sourceTitle = (id: string) =>
    (sheets.data ?? []).find((x) => x.id === id)?.title ?? id.slice(0, 8);
  const rendering = render.isPending || (job.data && job.data.status !== 'succeeded' && job.data.status !== 'failed');

  return (
    <div className="mx-auto max-w-5xl">
      {/* `data-no-print`: a breadcrumb is a way back, and paper has none. */}
      <Breadcrumb
        className="mb-2"
        data-no-print
        label={a11y('breadcrumb')}
        items={[
          { label: tnav('sheets'), href: '/sheets', key: 'sheets' },
          { label: s.title, key: 'sheet' },
        ]}
        renderLink={(item, children) => <Link href={item.href!}>{children}</Link>}
      />
      <header className="mb-6 flex flex-wrap items-start justify-between gap-3" data-no-print>
        <div>
          <h1>{s.title}</h1>
          <p className="text-body-s text-ink-500">
            {/* The layout version is not trivia: a scan is registered against
                the layout its sheet was printed with. */}
            <span className="mono">{s.layout_version}</span>
            {` · ${s.language.toUpperCase()}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={printPreview} leadingIcon={<IconPrint />} variant="secondary">
            {t('print')}
          </Button>
          <Button
            variant="primary"
            leadingIcon={<IconDownload />}
            loading={Boolean(rendering)}
            busyLabel={t('generating')}
            onClick={() =>
              render.mutate(sheetId, { onSuccess: (j) => setJobId(j.id) })
            }
          >
            {t('generatePdf')}
          </Button>
        </div>
      </header>

      {/* What this sheet IS, in the vocabulary of the programme: what it
          covers, what it answers, and where its corrections are. All three
          were reachable from the API and shown nowhere. */}
      <Panel className="mb-4 flex flex-col gap-3" data-no-print>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-label uppercase text-ink-500">{tsheet('filedUnder')}</span>
          {homeTheme ? (
            <Link href={`/classes/${s.class_id}/themes/${s.chapter_id}`}>
              {homeTheme}
            </Link>
          ) : (
            <span className="text-body-s text-ink-500">{tt('unfiled')}</span>
          )}
        </div>

        {/* Derived from the items, never stored — so it cannot describe a
            sheet that has since been edited (D71). */}
        {coverage.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-label uppercase text-ink-500">{tsheet('covers')}</span>
            {coverage.map((c) => (
              <ConceptTag key={c.competency_id} code={c.code} />
            ))}
          </div>
        ) : null}

        {/* The principal source is entry 0 of the same set (D70). */}
        {s.source_sheet_ids.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-label uppercase text-ink-500">{tsheet('answers')}</span>
            {s.source_sheet_ids.map((id, index) => (
              <span key={id} className="flex items-center gap-1">
                <Link href={`/sheets/${id}`}>{sourceTitle(id)}</Link>
                {index === 0 && s.source_sheet_ids.length > 1 ? (
                  <Chip>{tsheet('principal')}</Chip>
                ) : null}
              </span>
            ))}
          </div>
        ) : null}

        {/* A corrected sheet IS the confirmed scan: there is no separate
            entity, so this is the route from a sheet to its corrections. */}
        {s.scans.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-label uppercase text-ink-500">
              {tsheet('corrections')}
            </span>
            {s.scans.map((scan) => (
              <Link key={scan.id} href={`/scans/${scan.id}`}>
                {scan.confirmed_at
                  ? scan.revised
                    ? tsheet('scanRevised')
                    : tsheet('scanConfirmed')
                  : tsheet('scanPending')}
              </Link>
            ))}
          </div>
        ) : null}

        {/* The class as a whole on this paper — the altitude the model was
            missing, and the same roll-up the profile shows per pupil. */}
        {mastery.data && mastery.data.competency_ids.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-label uppercase text-ink-500">{tsheet('classBand')}</span>
            <MasteryBandTag
              band={mastery.data.overall.band as MasteryBand}
              label={bandLabels[mastery.data.overall.band as MasteryBand]}
              caption={
                mastery.data.overall.child_count > 0 &&
                mastery.data.overall.assessed_count < mastery.data.overall.child_count
                  ? tm('coverage', {
                      assessed: mastery.data.overall.assessed_count,
                      total: mastery.data.overall.child_count,
                    })
                  : undefined
              }
            />
          </div>
        ) : null}
      </Panel>

      {/* Always two documents. A design that produces only the first has failed. */}
      <Panel className="mb-4" data-no-print>
        <p className="text-body-s text-ink-700">{t('bothSheets')}</p>
        {s.blank_pdf_url || s.answer_key_pdf_url ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {s.blank_pdf_url ? (
              <a
                href={s.blank_pdf_url}
                className="no-underline"
                // Taking the blank sheet IS the print. `rendered_at` records
                // when the PDF was built, which is often days earlier — a
                // teacher renders on Sunday and prints on Tuesday — so this is
                // the only moment the agenda can call "printed". Fire and
                // forget: the download must not wait on the bookkeeping.
                onClick={() => markPrinted.mutate(s.id)}
              >
                <Button variant="secondary" leadingIcon={<IconDownload />}>
                  {t('downloadBlank')}
                </Button>
              </a>
            ) : null}
            {s.answer_key_pdf_url ? (
              <a href={s.answer_key_pdf_url} className="no-underline">
                <Button variant="secondary" leadingIcon={<IconDownload />}>
                  {t('downloadKey')}
                </Button>
              </a>
            ) : null}
          </div>
        ) : null}
        {job.data?.status === 'running' ? (
          <p className="mt-2 text-body-s text-ink-500" role="status">
            {t('generatingProgress', {
              percent: fmt.percent(job.data.progress ?? 0),
            })}
          </p>
        ) : null}
      </Panel>

      <Tabs value={kind} onValueChange={(next) => setKind(next as PreviewKind)}>
        <TabsList data-no-print>
          <TabsTrigger value="blank">{t('blank')}</TabsTrigger>
          <TabsTrigger value="key">{t('answerKey')}</TabsTrigger>
        </TabsList>

        {(['blank', 'key'] as const).map((tab) => (
          <TabsContent key={tab} value={tab}>
            {/* On a phone the A4 page is scaled to fit rather than making the
                body scroll sideways. */}
            <div className="overflow-x-auto">
              <div className="origin-top-left scale-[0.42] sm:scale-[0.6] md:scale-100">
                <Card flush>
                  <SheetPreview
                    sheet={s}
                    showKey={tab === 'key'}
                    frameRef={(el) => {
                      frames.current[tab] = el;
                    }}
                  />
                </Card>
              </div>
            </div>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}

type PreviewKind = 'blank' | 'key';

function previewUrl(sheetId: string, kind: PreviewKind): string {
  return `${API_BASE}/sheets/${sheetId}/preview${kind === 'key' ? '?kind=answer_key' : ''}`;
}

function SheetPreview({
  sheet,
  showKey,
  frameRef,
}: {
  sheet: NonNullable<ReturnType<typeof useSheet>['data']>;
  showKey: boolean;
  frameRef: (el: HTMLIFrameElement | null) => void;
}) {
  const t = useTranslations('sheets');
  const tcode = useTranslations('errors.code');
  const [error, setError] = useState<string | null>(null);

  // The server renders the document the PDF is made from, using the same
  // print.css and the same millimetre geometry out of layout.py. Showing it
  // directly is the only way the preview cannot drift from the paper.
  //
  // This used to be a hand-rolled React approximation: it put the answer
  // bubbles inline beside each option instead of on the fixed grid the
  // detector reads, printed no UID grid at all, and hardcoded A/B/C/D where
  // the sheet prints V/F. A teacher checking their sheet before printing 72
  // pages was checking something else.
  const src = previewUrl(sheet.id, showKey ? 'key' : 'blank');

  // A sheet the renderer refuses — a statement taller than the page, a class
  // with no students — answers 422 with `sheet_not_renderable`. Read the code
  // and localise it: an iframe would otherwise render the raw error JSON at
  // the teacher, and `message` is the API's own English, for the console
  // (`lib/api/client.ts`). `DraftPreview` does the same thing on the draft.
  useEffect(() => {
    let cancelled = false;
    setError(null);
    void fetch(src, { credentials: 'include' })
      .then(async (r) => {
        if (cancelled || r.ok) return;
        const body = (await r.json().catch(() => null)) as Partial<ApiErrorBody> | null;
        const failure = body?.error
          ? new ApiError(r.status, body.error.code ?? 'http_error', body.error.message ?? '')
          : null;
        setError(apiErrorMessage(failure, tcode) || t('previewUnavailable'));
      })
      .catch(() => {
        if (!cancelled) setError(t('previewUnavailable'));
      });
    return () => {
      cancelled = true;
    };
  }, [src, t, tcode]);

  if (error) {
    return (
      <p className="p-6 text-body-s text-danger-600" role="alert">
        {error}
      </p>
    );
  }

  return (
    <iframe
      ref={frameRef}
      src={src}
      title={showKey ? t('answerKey') : t('blank')}
      className="h-[297mm] w-[210mm] border-0 bg-white"
      // Same-origin so the print stylesheet resolves and the page can reach
      // the frame's window; the document is ours. `allow-modals` is what lets
      // a sandboxed frame open the print dialog — without it the browser
      // silently ignores `print()` and the button does nothing.
      sandbox="allow-same-origin allow-modals"
    />
  );
}
