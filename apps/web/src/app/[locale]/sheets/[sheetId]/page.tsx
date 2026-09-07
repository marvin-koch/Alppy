'use client';

import {
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
import { useTranslations } from 'next-intl';
import { use, useEffect, useRef, useState } from 'react';

import { API_BASE } from '@/lib/api/client';
import { useJob, useMarkPrinted, useRenderSheet, useSheet } from '@/lib/api/queries';
import { useFormatters } from '@/lib/format';

export default function SheetPage({ params }: { params: Promise<{ sheetId: string }> }) {
  const { sheetId } = use(params);
  const t = useTranslations('sheets');
  const fmt = useFormatters();
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');

  const sheet = useSheet(sheetId);
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
  const rendering = render.isPending || (job.data && job.data.status !== 'succeeded' && job.data.status !== 'failed');

  return (
    <div className="mx-auto max-w-5xl">
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
  // with no students — answers 422 with the reason. Read it and show it: an
  // iframe would otherwise render the raw error JSON at the teacher.
  useEffect(() => {
    let cancelled = false;
    setError(null);
    void fetch(src, { credentials: 'include' })
      .then(async (r) => {
        if (cancelled || r.ok) return;
        const body = await r.json().catch(() => null);
        setError(body?.error?.message ?? t('previewUnavailable'));
      })
      .catch(() => {
        if (!cancelled) setError(t('previewUnavailable'));
      });
    return () => {
      cancelled = true;
    };
  }, [src, t]);

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
