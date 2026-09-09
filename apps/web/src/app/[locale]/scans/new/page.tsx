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
import { useScope } from '@/lib/scope';

export default function NewScanPage() {
  const t = useTranslations('scans');
  const tc = useTranslations('common');
  const tErr = useTranslations('errors.code');
  const router = useRouter();
  const { classId, subjectId } = useScope();
  // Scoped, not the whole school: uploading a pile means choosing the sheet it
  // was printed from, and an unscoped list offered a colleague's sheets in
  // another Branch — which the API now refuses anyway (D75).
  const sheets = useSheets(classId ?? undefined, subjectId ?? undefined);
  const classes = useClasses();
  const upload = useUploadScan();
  const [sheetId, setSheetId] = useState<Uuid | ''>('');
  const [error, setError] = useState<string | null>(null);
  //  How many files are in flight, so the wait can name them.
  const [pending, setPending] = useState(0);

  // Only a sheet that has been rendered can have copies coming back.
  const printable = (sheets.data ?? []).filter((s) => s.rendered_at !== null);

  function onFiles(files: File[]) {
    if (files.length === 0) return;
    if (!sheetId) {
      setError(t('chooseSheetFirst'));
      return;
    }
    setError(null);
    setPending(files.length);
    upload.mutate(
      { files, sheetId },
      {
        onSuccess: (scan) =>
          router.push(
            scan.job_id ? `/scans/${scan.id}?job=${scan.job_id}` : `/scans/${scan.id}`,
          ),
        onError: (e) => {
          setPending(0);
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
