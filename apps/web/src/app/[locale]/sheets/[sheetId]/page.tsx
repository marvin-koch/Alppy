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
import { apiErrorMessage, requestIdOf } from '@/lib/api/error-message';
import type { ApiErrorBody } from '@/lib/api/types';
import { useBandLabels } from '@/lib/bands';
import { printReadiness } from '@/lib/print';
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

  // Which document the teacher is looking at. The frame is an APERÇU and
  // nothing else: it is not printed, and there is no longer any code that
  // prints it.
  //
  // It used to be the print path — `frame.contentWindow.print()`, then
  // `markPrinted`. That produced paper the grading pipeline had no coordinates
  // for, because `GET /sheets/{id}/preview` renders the stored rows and writes
  // nothing, while `AnswerBoxPlacement` — the rectangles a written answer is
  // cropped from — is written only by `render_sheet`. A fiche with four open
  // items could be printed, sat by twenty-four pupils, photographed, and come
  // back with all ninety-six written answers "à reprendre à la main", with
  // nothing anywhere saying the fix had been a different button two days
  // earlier. And there is no migration for paper.
  //
  // So: one door, the PDF. `lib/print.ts` is the gate; see it for why
  // `rendered_at` is the whole of the question.
  const [kind, setKind] = useState<PreviewKind>('blank');

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
        requestId={requestIdOf(sheet.error)}
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
  const rendering =
    render.isPending ||
    (job.data && job.data.status !== 'succeeded' && job.data.status !== 'failed');
  const print = printReadiness(s, { rendering: Boolean(rendering) });

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
          {/* `printed_at` was in the contract with no reader anywhere (G23).
              It is a different fact from `rendered_at` — a PDF that exists is not
              a pile of paper on a desk — and it is the one a teacher needs to
              answer "have I already handed these out?" before generating again. */}
          {s.printed_at ? (
            <p className="text-body-s text-ink-500" data-printed-at>
              {t('printedOn', { date: fmt.dateLong(s.printed_at) })}
            </p>
          ) : null}
        </div>
        {/* One action, and which one it is says what state the paper is in.
            A sheet whose PDF is current prints it; a sheet whose PDF is
            missing or was invalidated by an edit builds it first. There is no
            third button that prints something else. */}
        <div className="flex flex-wrap items-center gap-2">
          {print.state === 'ready' ? (
            <a
              href={print.pdfUrl ?? undefined}
              target="_blank"
              rel="noopener"
              className="no-underline"
              // Taking the blank sheet IS the print (the same reasoning as the
              // download button below), and this is now the only path that can
              // record one — every sheet marked printed has passed the render
              // gate, so the agenda cannot carry a print that produced paper
              // nothing could grade.
              onClick={() => markPrinted.mutate(s.id)}
            >
              <Button variant="primary" leadingIcon={<IconPrint />}>
                {t('print')}
              </Button>
            </a>
          ) : (
            <Button
              variant="primary"
              leadingIcon={<IconDownload />}
              loading={print.state === 'rendering'}
              busyLabel={t('generating')}
              onClick={() => render.mutate(sheetId, { onSuccess: (j) => setJobId(j.id) })}
            >
              {t('generatePdf')}
            </Button>
          )}
        </div>
      </header>

      {/* What this sheet IS, in the vocabulary of the programme: what it
          covers, what it answers, and where its corrections are. All three
          were reachable from the API and shown nowhere. */}
      <Panel className="mb-4 flex flex-col gap-3" data-no-print>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-label uppercase text-ink-500">{tsheet('filedUnder')}</span>
          {homeTheme ? (
            <Link href={`/classes/${s.class_id}/themes/${s.chapter_id}`}>{homeTheme}</Link>
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
            <span className="text-label uppercase text-ink-500">{tsheet('corrections')}</span>
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
        {/* Why the button above says "Générer" and not "Imprimer". A refusal a
            teacher can read beats paper they cannot grade — and the open-item
            case gets the sentence that names the consequence, because that is
            the one where the cost is a class set of answers nobody can mark. */}
        {print.state !== 'ready' ? (
          <p className="mt-2 text-body-s text-ink-500">
            {print.hasOpenItems ? t('printNeedsPdfOpen') : t('printNeedsPdf')}
          </p>
        ) : null}
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
                  <SheetPreview sheet={s} showKey={tab === 'key'} />
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

/** Long enough that a slow render is not called a failure, short enough that
 *  a teacher does not stand in front of a class watching a blank rectangle. */
const PREVIEW_TIMEOUT_MS = 8000;

function previewUrl(sheetId: string, kind: PreviewKind): string {
  return `${API_BASE}/sheets/${sheetId}/preview${kind === 'key' ? '?kind=answer_key' : ''}`;
}

function SheetPreview({
  sheet,
  showKey,
}: {
  sheet: NonNullable<ReturnType<typeof useSheet>['data']>;
  showKey: boolean;
}) {
  const t = useTranslations('sheets');
  const tcode = useTranslations('errors.code');
  const [error, setError] = useState<string | null>(null);
  // A ref, not state: the timeout below reads it when it fires, and a state
  // value would be the one captured when the timer was armed — always false.
  const loaded = useRef(false);

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

  // The fetch above proves the API answered. It does NOT prove the browser let
  // the frame display the answer, and those are different questions: when the
  // web app and the API are on different origins — the compose default — the
  // document is fetched fine (`connect-src` names the API) and the frame is
  // blocked (`frame-src` did not), so the preview was blank, silent, and
  // indistinguishable from a sheet that renders nothing. `frame-src` now
  // carries the API origin, so this is the belt to that braces: a violation
  // fires an event, and this listens for it rather than showing the teacher an
  // empty A4 and letting them conclude the fiche is empty.
  useEffect(() => {
    const onViolation = (event: SecurityPolicyViolationEvent) => {
      if (!event.effectiveDirective.startsWith('frame-src')) return;
      setError(t('previewBlocked'));
    };
    document.addEventListener('securitypolicyviolation', onViolation);
    return () => document.removeEventListener('securitypolicyviolation', onViolation);
  }, [t]);

  // And the case with no event at all: a frame that never loads. A preview
  // that is merely slow resolves long before this; one that is never coming
  // says so, instead of leaving a blank page on a projector.
  useEffect(() => {
    loaded.current = false;
    const timer = window.setTimeout(() => {
      if (loaded.current) return;
      setError((current) => current ?? t('previewUnavailable'));
    }, PREVIEW_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
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
      src={src}
      title={showKey ? t('answerKey') : t('blank')}
      className="h-[297mm] w-[210mm] border-0 bg-white"
      // Same-origin so the print stylesheet resolves; the document is ours.
      // `allow-modals` used to be here so the frame could open a print dialog.
      // Nothing prints the frame any more — it is an aperçu, and the paper
      // comes from the PDF — so the frame no longer needs to be driven at all.
      sandbox="allow-same-origin"
      onLoad={(event) => {
        loaded.current = true;
        // Best effort, and only same-origin: a frame that loaded an empty
        // document is a frame that displayed nothing. Cross-origin this throws
        // (or reads null), which is not evidence of failure — so it is only
        // ever used to raise an error, never to clear one.
        try {
          const doc = event.currentTarget.contentDocument;
          if (doc && doc.body && doc.body.childElementCount === 0) {
            setError(t('previewUnavailable'));
          }
        } catch {
          /* cross-origin: nothing to read, and nothing to conclude. */
        }
      }}
    />
  );
}
