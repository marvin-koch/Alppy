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
import { use, useEffect, useState } from 'react';

import { API_BASE } from '@/lib/api/client';
import { useJob, useRenderSheet, useSheet } from '@/lib/api/queries';
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
          <Button
            onClick={() => window.print()}
            leadingIcon={<IconPrint />}
            variant="secondary"
          >
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
              <a href={s.blank_pdf_url} className="no-underline">
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

      <Tabs defaultValue="blank">
        <TabsList data-no-print>
          <TabsTrigger value="blank">{t('blank')}</TabsTrigger>
          <TabsTrigger value="key">{t('answerKey')}</TabsTrigger>
        </TabsList>

        {(['blank', 'key'] as const).map((kind) => (
          <TabsContent key={kind} value={kind}>
            {/* On a phone the A4 page is scaled to fit rather than making the
                body scroll sideways. */}
            <div className="overflow-x-auto">
              <div className="origin-top-left scale-[0.42] sm:scale-[0.6] md:scale-100">
                <Card flush>
                  <SheetPreview sheet={s} showKey={kind === 'key'} />
                </Card>
              </div>
            </div>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}

function SheetPreview({
  sheet,
  showKey,
}: {
  sheet: NonNullable<ReturnType<typeof useSheet>['data']>;
  showKey: boolean;
}) {
  const t = useTranslations('sheets');

  // The server renders the document the PDF is made from, using the same
  // print.css and the same millimetre geometry out of layout.py. Showing it
  // directly is the only way the preview cannot drift from the paper.
  //
  // This used to be a hand-rolled React approximation: it put the answer
  // bubbles inline beside each option instead of on the fixed grid the
  // detector reads, printed no UID grid at all, and hardcoded A/B/C/D where
  // the sheet prints V/F. A teacher checking their sheet before printing 72
  // pages was checking something else.
  const src = `${API_BASE}/sheets/${sheet.id}/preview${showKey ? '?kind=answer_key' : ''}`;

  return (
    <iframe
      src={src}
      title={showKey ? t('answerKey') : t('blank')}
      className="h-[297mm] w-[210mm] border-0 bg-white"
      // Same-origin so the print stylesheet resolves; the document is ours.
      sandbox="allow-same-origin"
    />
  );
}
