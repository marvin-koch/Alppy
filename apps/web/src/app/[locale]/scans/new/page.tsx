'use client';

import {
  Button,
  Card,
  EmptyState,
  Field,
  FileDrop,
  IlloTray,
  LoadingState,
  Panel,
  Select,
  Spinner,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useRouter } from '@/i18n/navigation';
import { apiErrorMessage } from '@/lib/api/error-message';
import { useClasses, useSheets, useUploadScan } from '@/lib/api/queries';
import type { Uuid } from '@/lib/api/types';
import { downscaleAll } from '@/lib/downscale';
import { useIdempotencyKey } from '@/lib/idempotency';
import { useScope } from '@/lib/scope';

/**
 * Client-side limits, and what they are for.
 *
 * A courtesy and never a control — the same framing `sources/page.tsx` uses. The
 * API validates all three again, and it is the API's answer that decides. What
 * these buy is a specific message in under a second instead of a two-minute
 * upload that ends in a 413.
 *
 * `MAX_PAGES` mirrors the API's own cap on a pile. `MAX_MB` is per file and
 * applies AFTER the downscale, so a 12 MP photograph is measured at the size it
 * will actually be sent at rather than rejected for a size it was never going to
 * be uploaded at.
 */
const MAX_PAGES = 120;
const MAX_MB = 25;

export default function NewScanPage() {
  const t = useTranslations('scans');
  const tc = useTranslations('common');
  const tErr = useTranslations('errors.code');
  const te = useTranslations('errors.generic');
  const router = useRouter();
  const { classId, subjectId } = useScope();
  // Scoped, not the whole school: uploading a pile means choosing the sheet it
  // was printed from, and an unscoped list offered a colleague's sheets in
  // another Branch — which the API now refuses anyway (D75).
  const sheets = useSheets(classId ?? undefined, subjectId ?? undefined);
  const classes = useClasses();
  // Owned here rather than inside the hook, because THIS screen is the one that
  // knows when a retry stops being a retry: choosing different photographs is a
  // new intention, and reusing the key would have the server answer with the
  // pile built from the previous selection.
  const intent = useIdempotencyKey();
  const upload = useUploadScan(intent);
  const [sheetId, setSheetId] = useState<Uuid | ''>('');
  const [error, setError] = useState<string | null>(null);
  //  How many files are in flight, so the wait can name them.
  const [pending, setPending] = useState(0);
  // What is actually being sent, by name. `FileDrop` has always known the list
  // and the screen showed one aggregate count, so a pile of 28 photographs
  // reported "Envoi de 28 copies…" for two minutes with no way to tell a slow
  // upload from a stalled one (F10). The real fix for a dropped connection is
  // a resumable upload and belongs in the API; naming the files is the half
  // the client owns.
  const [sending, setSending] = useState<string[]>([]);

  // Only a sheet that has been rendered can have copies coming back.
  const printable = (sheets.data ?? []).filter((s) => s.rendered_at !== null);

  /**
   * `FileDrop` wants a `void` handler and the work is asynchronous, so the
   * boundary is explicit rather than a floating promise. Nothing in `send`
   * throws by design — `downscaleAll` returns the original file on every failure
   * — and this is here for what design does not cover.
   */
  function onFiles(files: File[]) {
    void send(files).catch(() => {
      setPending(0);
      setSending([]);
      setError(te('body'));
    });
  }

  async function send(files: File[]) {
    if (files.length === 0) return;
    if (!sheetId) {
      setError(t('chooseSheetFirst'));
      return;
    }
    if (files.length > MAX_PAGES) {
      setError(t('tooManyFiles', { max: MAX_PAGES, count: files.length }));
      return;
    }
    const wrongType = files.find(
      (file) => file.type !== 'application/pdf' && !file.type.startsWith('image/'),
    );
    if (wrongType) {
      setError(t('fileWrongType', { name: wrongType.name }));
      return;
    }
    // A fresh selection, so a fresh key. A retry of THIS selection goes through
    // `upload.mutate` again without coming back here, and keeps the key.
    intent.restart();
    setError(null);
    setPending(files.length);
    setSending(files.map((file) => file.name));

    // Shrunk before the size check, so a 12 MP photograph is judged at the size
    // it will be sent at. Every failure path inside returns the original file, so
    // this can slow an upload down but never stop one.
    const prepared = await downscaleAll(files);
    const tooBig = prepared.find((file) => file.size > MAX_MB * 1024 * 1024);
    if (tooBig) {
      setPending(0);
      setSending([]);
      setError(t('fileTooLarge', { name: tooBig.name, max: MAX_MB }));
      return;
    }

    upload.mutate(
      { files: prepared, sheetId },
      {
        onSuccess: (scan) =>
          router.push(scan.job_id ? `/scans/${scan.id}?job=${scan.job_id}` : `/scans/${scan.id}`),
        onError: (e) => {
          setPending(0);
          setSending([]);
          setError(apiErrorMessage(e, tErr));
        },
      },
    );
  }

  const classCode = new Map((classes.data ?? []).map((c) => [c.id, c.code]));

  if (sheets.isLoading) return <LoadingState shape="list" label={tc('loading')} rows={3} />;

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6">{t('title')}</h1>

      {printable.length === 0 ? (
        <EmptyState
          illustration={<IlloTray />}
          title={t('noSheets.title')}
          description={t('noSheets.body')}
          action={
            <Button variant="primary" onClick={() => router.push('/sheets/new')}>
              {t('noSheets.action')}
            </Button>
          }
        />
      ) : (
        <>
          <Card>
            {/* Which sheet these are copies of is something only the teacher
                knows, and without it the pipeline can read every mark and grade
                nothing. Asking is the whole cost of never losing a class's work. */}
            <Field label={t('sheet')} help={t('sheetHelp')} required requiredLabel={tc('required')}>
              <Select
                value={sheetId}
                onChange={(e) => {
                  setSheetId(e.target.value);
                  setError(null);
                }}
              >
                <option value="">{t('chooseSheet')}</option>
                {printable.map((sheet) => (
                  <option key={sheet.id} value={sheet.id}>
                    {sheet.title} · {classCode.get(sheet.class_id) ?? ''}
                  </option>
                ))}
              </Select>
            </Field>

            <div className="mt-4">
              {/* `camera` opens the phone's camera directly: photographing the
                  pile of copies is the real classroom workflow, not a fallback.
                  Several photos are one pile, not one scan each. */}
              <FileDrop
                label={t('upload')}
                description={t('uploadHelp')}
                accept="application/pdf,image/*"
                multiple
                camera
                cameraLabel={t('takePhoto')}
                onFiles={onFiles}
                disabled={upload.isPending || !sheetId}
                invalid={Boolean(error)}
              />
            </div>

            {upload.isPending ? (
              // A pile of 28 photos is tens of megabytes: this is the longest
              // wait in the product and it used to be one grey line of text.
              // A teacher who cannot tell whether anything is happening takes
              // the phone away, and the upload dies with the page.
              <Panel className="mt-3 flex items-center gap-3" role="status" aria-live="polite">
                {/* A spinner, not a ring: nobody is measuring how much of the
                    upload is done, and a meter drawn at 0 says "nothing has
                    happened", which is both wrong and discouraging. */}
                <Spinner size={28} className="shrink-0 text-primary-600" />
                <div className="min-w-0">
                  <p className="text-body-s font-bold text-ink-900">
                    {t('uploadingCount', { count: pending })}
                  </p>
                  <p className="text-body-s text-ink-500">{t('uploadingHelp')}</p>
                  {/* The pile is ONE request, so there is no per-file
                      progress to report honestly — what there is, is which
                      files are in it. A teacher who can see the names knows
                      the right photographs were picked, which is the question
                      they actually have while waiting. */}
                  {sending.length > 0 ? (
                    <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                      {sending.map((name) => (
                        <li key={name} className="truncate text-body-s text-ink-500">
                          {name}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </Panel>
            ) : null}
            {error ? (
              <p className="mt-3 text-body-s text-danger-600" role="alert">
                {error}
              </p>
            ) : null}
          </Card>

          {!upload.isPending && !error ? (
            <div className="mt-6">
              <EmptyState
                illustration={<IlloTray />}
                title={t('empty.title')}
                description={t('empty.body')}
                size="sm"
              />
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
