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
import { use, useState } from 'react';

import { useJob, useRenderSheet, useSheet } from '@/lib/api/queries';

export default function SheetPage({ params }: { params: Promise<{ sheetId: string }> }) {
  const { sheetId } = use(params);
  const t = useTranslations('sheets');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');

  const sheet = useSheet(sheetId);
  const render = useRenderSheet();
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);

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
            {t('generating')} — {Math.round((job.data.progress ?? 0) * 100)}%
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
  return (
    <div className="print-sheet">
      <article className="print-page">
        <span data-fiducial="tl" />
        <span data-fiducial="tr" />
        <span data-fiducial="bl" />
        <span data-fiducial="br" />

        <header className="print-header">
          <div>
            <p className="print-title">{sheet.title}</p>
            <p className="print-meta">{showKey ? t('answerKey') : t('blank')}</p>
          </div>
          <div className="print-uid">
            <span className="print-uid-text">
              {sheet.instances[0]?.student_uid ?? '________'}
            </span>
          </div>
        </header>

        <div className="print-frame">
          <ol className="list-none p-0">
            {sheet.items.map((item, i) => (
              <li key={item.id} className="print-item">
                <p className="print-item-statement">
                  <span className="mono mr-2">{i + 1}.</span>
                  {item.statement_override ?? item.exercise.statement}
                </p>
                {item.exercise.options ? (
                  <div className="print-answers">
                    {item.exercise.options.map((o, oi) => (
                      <span key={oi} className="print-bubble">
                        <span
                          className="print-bubble-mark"
                          data-key={
                            showKey && item.exercise.answer_index === oi ? 'true' : undefined
                          }
                        />
                        <span className="print-bubble-letter">{'ABCD'[oi]}</span>
                        <span>{o}</span>
                      </span>
                    ))}
                  </div>
                ) : null}
              </li>
            ))}
          </ol>
        </div>
      </article>
    </div>
  );
}
