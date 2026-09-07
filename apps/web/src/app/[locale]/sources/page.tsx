'use client';

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  FileDrop,
  IlloSheet,
  LoadingState,
  Panel,
  Select,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useSourceExercises, useSources, useSubjects, useUploadSource } from '@/lib/api/queries';
import { useFormatters } from '@/lib/format';
import type { SourceOut } from '@/lib/api/types';

const MAX_MB = 50;

export default function SourcesPage() {
  const t = useTranslations('sources');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const locale = useLocale();
  const subjects = useSubjects();
  const upload = useUploadSource();
  const [rejected, setRejected] = useState<string | null>(null);
  const [subjectId, setSubjectId] = useState('');

  // A source is only "done" once ingestion finishes, and that happens in the
  // worker. Poll while anything is still moving, then stop — a page that never
  // refreshes leaves the teacher looking at "indexing…" forever.
  const { data, isLoading, isError, refetch } = useSources();
  const pending = (data ?? []).some((s) => s.status === 'queued' || s.status === 'running');
  useEffect(() => {
    if (!pending) return;
    const id = setInterval(() => void refetch(), 2000);
    return () => clearInterval(id);
  }, [pending, refetch]);

  const activeSubject = subjectId || subjects.data?.[0]?.id || '';

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
    if (!activeSubject) return;
    setRejected(null);
    upload.mutate({ file, subjectId: activeSubject });
  }

  const sources = data ?? [];

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-6">{t('title')}</h1>

      <Card className="mb-6">
        <div className="mb-4 max-w-xs">
          <Field label={t('subject')} help={t('subjectHelp')}>
            <Select
              value={activeSubject}
              onChange={(e) => setSubjectId(e.currentTarget.value)}
              disabled={upload.isPending || !subjects.data?.length}
            >
              {(subjects.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.labels[locale] ?? s.labels.en ?? s.key}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <FileDrop
          label={t('upload')}
          description={t('uploadHelp')}
          accept="application/pdf"
          onFiles={onFiles}
          invalid={Boolean(rejected) || upload.isError}
          disabled={upload.isPending || !activeSubject}
        />
        {/* The rejection is a message, not a red border: colour is never the
            only channel. */}
        {rejected ? (
          <p className="mt-2 text-body-s text-danger-600" role="alert">
            {rejected}
          </p>
        ) : null}
        {/* A failed upload used to be invisible: the mutation had no error
            branch, so a 4xx looked exactly like nothing happening. */}
        {upload.isError && !rejected ? (
          <p className="mt-2 text-body-s text-danger-600" role="alert">
            {t('uploadFailed')}
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
              <SourceRow source={s} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SourceRow({ source }: { source: SourceOut }) {
  const t = useTranslations('sources');
  const tc = useTranslations('common');
  const fmt = useFormatters();
  const [open, setOpen] = useState(false);
  const exercises = useSourceExercises(open ? source.id : null);

  return (
    <Panel>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-bold">{source.filename}</p>
          <p className="text-body-s text-ink-500">
            {[
              source.page_count ? t('pages', { count: source.page_count }) : null,
              source.language ? source.language.toUpperCase() : null,
              fmt.date(source.created_at),
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <Badge
          variant={
            source.status === 'succeeded'
              ? 'success'
              : source.status === 'failed'
                ? 'danger'
                : 'neutral'
          }
        >
          {source.status === 'succeeded'
            ? t('indexed')
            : source.status === 'failed'
              ? t('failed')
              : t('indexing')}
        </Badge>
      </div>

      <p className="mt-2 text-body-s">
        {t('exercisesFound', { count: source.exercise_count ?? 0 })}
      </p>

      {source.error ? (
        <p className="mt-2 text-body-s text-danger-600" data-transcription>
          {source.error}
        </p>
      ) : null}

      {/* A green tick with zero exercises needs an explanation, or the teacher
          assumes the whole book was scanned. */}
      {source.notice ? (
        <p className="mt-2 text-body-s text-ink-700" data-transcription>
          <strong>{t('notice')} : </strong>
          {source.notice}
        </p>
      ) : null}

      {source.status === 'succeeded' && (source.exercise_count ?? 0) > 0 ? (
        <div className="mt-3">
          <Button variant="ghost" size="sm" onClick={() => setOpen((v) => !v)}>
            {open ? t('hideExercises') : t('showExercises')}
          </Button>
          {open ? (
            exercises.isLoading ? (
              <LoadingState shape="list" label={tc('loading')} rows={3} />
            ) : (
              <>
                <ol className="mt-3 flex list-decimal flex-col gap-2 pl-5">
                  {(exercises.data?.items ?? []).map((ex) => (
                    <li key={ex.id} className="text-body-s">
                      {ex.label ? <span className="mono mr-1 text-ink-700">{ex.label}</span> : null}
                      {ex.title ?? ex.statement}
                      {ex.source_page ? (
                        <span className="text-ink-500"> · p. {ex.source_page}</span>
                      ) : null}
                    </li>
                  ))}
                </ol>
                {/* The listing is paged now, so this preview shows the first
                    page and says so rather than implying it is the whole book.
                    Choosing from a document happens in the sheet builder. */}
                {(exercises.data?.total ?? 0) > (exercises.data?.items.length ?? 0) ? (
                  <p className="mt-2 text-body-s text-ink-500">
                    {t('showingFirst', {
                      shown: exercises.data?.items.length ?? 0,
                      total: exercises.data?.total ?? 0,
                    })}
                  </p>
                ) : null}
              </>
            )
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}
