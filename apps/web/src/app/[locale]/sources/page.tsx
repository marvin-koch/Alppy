'use client';

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  FileDrop,
  IlloSheet,
  LoadingState,
  Panel,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useSources, useUploadSource } from '@/lib/api/queries';
import { useFormatters } from '@/lib/format';

const MAX_MB = 50;

export default function SourcesPage() {
  const t = useTranslations('sources');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const fmt = useFormatters();
  const { data, isLoading, isError, refetch } = useSources();
  const upload = useUploadSource();
  const [rejected, setRejected] = useState<string | null>(null);

  function onFiles(files: File[]) {
    const file = files[0];
    if (!file) return;
    // Validated here for a fast, specific message; the API validates again,
    // because a client check is a courtesy and never a control.
    if (file.size > MAX_MB * 1024 * 1024) {
      setRejected(t('fileTooLarge', { max: MAX_MB }));
      return;
    }
    if (file.type !== 'application/pdf') {
      setRejected(t('fileWrongType'));
      return;
    }
    setRejected(null);
    upload.mutate(file);
  }

  const sources = data ?? [];

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-6">{t('title')}</h1>

      <Card className="mb-6">
        <FileDrop
          label={t('upload')}
          description={t('uploadHelp')}
          accept="application/pdf"
          onFiles={onFiles}
          invalid={Boolean(rejected)}
          disabled={upload.isPending}
        />
        {/* The rejection is a message, not a red border: colour is never the
            only channel. */}
        {rejected ? (
          <p className="mt-2 text-body-s text-danger-600" role="alert">
            {rejected}
          </p>
        ) : null}
        {upload.isPending ? (
          <p className="mt-2 text-body-s text-ink-500" role="status">
            {t('uploading')}
          </p>
        ) : null}
      </Card>

      {isLoading ? (
        <LoadingState shape="list" label={tc('loading')} rows={3} />
      ) : isError ? (
        <ErrorState
          title={te('title')}
          description={te('body')}
          action={<Button onClick={() => void refetch()}>{tc('retry')}</Button>}
        />
      ) : sources.length === 0 ? (
        <EmptyState
          illustration={<IlloSheet />}
          title={t('empty.title')}
          description={t('empty.body')}
        />
      ) : (
        <ul className="flex list-none flex-col gap-3 p-0">
          {sources.map((s) => (
            <li key={s.id}>
              <Panel>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-bold">{s.filename}</p>
                    <p className="text-body-s text-ink-500">
                      {s.page_count ? t('pages', { count: s.page_count }) : null}
                      {s.language ? ` · ${s.language.toUpperCase()}` : null}
                      {` · ${fmt.date(s.created_at)}`}
                    </p>
                  </div>
                  <Badge
                    variant={
                      s.status === 'succeeded'
                        ? 'success'
                        : s.status === 'failed'
                          ? 'danger'
                          : 'neutral'
                    }
                  >
                    {s.status === 'succeeded'
                      ? t('indexed')
                      : s.status === 'failed'
                        ? t('failed')
                        : t('indexing')}
                  </Badge>
                </div>
                <p className="mt-2 text-body-s">
                  {t('exercisesFound', { count: s.exercise_count ?? 0 })}
                </p>
                {s.error ? (
                  <p className="mt-2 text-body-s text-danger-600" data-transcription>
                    {s.error}
                  </p>
                ) : null}
              </Panel>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
