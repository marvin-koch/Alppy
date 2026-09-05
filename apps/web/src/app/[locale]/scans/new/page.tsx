'use client';

import { Card, EmptyState, FileDrop, IlloTray } from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useRouter } from '@/i18n/navigation';
import { useUploadScan } from '@/lib/api/queries';

export default function NewScanPage() {
  const t = useTranslations('scans');
  const router = useRouter();
  const upload = useUploadScan();
  const [error, setError] = useState<string | null>(null);

  function onFiles(files: File[]) {
    if (files.length === 0) return;
    setError(null);
    upload.mutate(
      { files },
      {
        onSuccess: (result) => {
          if ('pages' in result) router.push(`/scans/${result.id}`);
          else router.push(`/scans/${result.id}`);
        },
        onError: (e) => setError(e instanceof Error ? e.message : String(e)),
      },
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6">{t('title')}</h1>
      <Card>
        {/* `camera` opens the phone's camera directly: photographing the pile of
            copies is the real classroom workflow, not a fallback. */}
        <FileDrop
          label={t('upload')}
          description={t('uploadHelp')}
          accept="application/pdf,image/*"
          multiple
          camera
          cameraLabel={t('takePhoto')}
          onFiles={onFiles}
          disabled={upload.isPending}
          invalid={Boolean(error)}
        />
        {upload.isPending ? (
          <p className="mt-3 text-body-s text-ink-500" role="status">
            {t('processing')}
          </p>
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
    </div>
  );
}
