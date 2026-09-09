'use client';

import { Breadcrumb, Button, Card, ErrorState, Field, Input, LoadingState } from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { use, useState } from 'react';

import { ConfirmDestructive } from '@/components/ConfirmDestructive';
import { LockedValue } from '@/components/LockedValue';
import { apiErrorMessage } from '@/lib/api/error-message';
import {
  useChapters,
  useDeleteChapter,
  useDeleteSource,
  useSources,
  useSubjects,
  useUpdateChapter,
  useUpdateSource,
} from '@/lib/api/queries';
import type { ChapterOut, SourceOut, Uuid } from '@/lib/api/types';

/**
 * One Branch's Themes and textbooks — the two things a teacher curates.
 *
 * They share a screen because they are the same job seen twice: what this
 * Branch is made of. And they share a refusal shape — neither delete asks
 * "are you sure?", both report a COUNT of what still points at the row, which
 * is the only thing that lets a teacher decide.
 *
 * The `unfiled` bucket is listed and visibly undeletable. It is recognised by
 * `primary_competency_id === null`, never by its key: a school may relabel it,
 * and a rename must not make it deletable.
 */
export default function BranchSettingsPage({
  params,
}: {
  params: Promise<{ subjectId: string }>;
}) {
  const { subjectId } = use(params);
  const t = useTranslations('settings');
  const tc = useTranslations('common');
  const tcode = useTranslations('errors.code');
  const te = useTranslations('errors.generic');
  const ta = useTranslations('a11y');
  const locale = useLocale();

  const subjects = useSubjects();
  const chapters = useChapters(subjectId as Uuid);
  const sources = useSources();

  const updateChapter = useUpdateChapter();
  const removeChapter = useDeleteChapter();
  const updateSource = useUpdateSource();
  const removeSource = useDeleteSource();

  const [editingTheme, setEditingTheme] = useState<Uuid | null>(null);
  const [themeName, setThemeName] = useState('');
  const [deletingTheme, setDeletingTheme] = useState<ChapterOut | null>(null);
  const [editingBook, setEditingBook] = useState<Uuid | null>(null);
  const [bookTitle, setBookTitle] = useState('');
  const [bookPublisher, setBookPublisher] = useState('');
  const [bookIsbn, setBookIsbn] = useState('');
  const [bookUrl, setBookUrl] = useState('');
  const [deletingBook, setDeletingBook] = useState<SourceOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const subject = (subjects.data ?? []).find((s) => s.id === subjectId);
  const subjectName = subject?.labels?.[locale] ?? subject?.labels?.fr ?? subject?.key ?? '';
  const label = (row: { labels?: Record<string, string>; key: string }) =>
    row.labels?.[locale] ?? row.labels?.fr ?? row.key;
  const books = (sources.data ?? []).filter((s) => s.subject_id === subjectId);

  if (chapters.isLoading || subjects.isLoading) {
    return <LoadingState shape="list" label={tc('loading')} rows={4} />;
  }
  if (chapters.isError) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={<Button onClick={() => void chapters.refetch()}>{tc('retry')}</Button>}
      />
    );
  }

  function report(caught: unknown) {
    setError(apiErrorMessage(caught, tcode));
  }

  return (
    <div className="mx-auto max-w-4xl">
      <Breadcrumb
        className="mb-2"
        label={ta('breadcrumb')}
        items={[
          { label: t('title'), href: '/settings', key: 'settings' },
          { label: subjectName, key: 'branch' },
        ]}
      />
      <h1 className="mb-6">{t('manageBranch')}</h1>

      <div className="flex flex-col gap-6">
        <Card className="flex flex-col gap-3">
          <h2 className="text-h3">{t('themes')}</h2>
          <ul className="flex flex-col gap-2">
            {(chapters.data ?? []).map((chapter) => {
              const unfiled = chapter.primary_competency_id === null;
              return (
                <li
                  key={chapter.id}
                  className="flex min-h-11 flex-wrap items-center gap-3 rounded-md border border-line bg-surface px-4 py-2"
                >
                  {editingTheme === chapter.id ? (
                    <>
                      <Input
                        className="flex-1"
                        value={themeName}
                        onChange={(e) => setThemeName(e.target.value)}
                      />
                      <Button variant="ghost" onClick={() => setEditingTheme(null)}>
                        {tc('cancel')}
                      </Button>
                      <Button
                        variant="primary"
                        onClick={() => {
                          setError(null);
                          updateChapter.mutate(
                            {
                              chapterId: chapter.id,
                              subjectId: subjectId as Uuid,
                              body: { labels: { ...chapter.labels, [locale]: themeName } },
                            },
                            { onSuccess: () => setEditingTheme(null), onError: report },
                          );
                        }}
                      >
                        {tc('save')}
                      </Button>
                    </>
                  ) : (
                    <>
                      <span
                        className={`min-w-0 flex-1 truncate font-semibold ${
                          unfiled ? 'text-ink-500' : ''
                        }`}
                      >
                        {label(chapter)}
                      </span>
                      {unfiled ? null : (
                        <>
                          <Button
                            variant="ghost"
                            onClick={() => {
                              setEditingTheme(chapter.id);
                              setThemeName(label(chapter));
                            }}
                          >
                            {t('rename')}
                          </Button>
                          <Button variant="ghost" onClick={() => setDeletingTheme(chapter)}>
                            {tc('delete')}
                          </Button>
                        </>
                      )}
                    </>
                  )}
                </li>
              );
            })}
          </ul>
          <p className="text-body-s text-ink-500">{t('unfiledLocked')}</p>
        </Card>

        <Card className="flex flex-col gap-3">
          <h2 className="text-h3">{t('textbooks')}</h2>
          <ul className="flex flex-col gap-2">
            {books.map((book) => (
              <li
                key={book.id}
                className="flex flex-col gap-2 rounded-md border border-line bg-surface p-4"
              >
                {editingBook === book.id ? (
                  <>
                    <Field label={t('bookTitle')}>
                      <Input
                        value={bookTitle}
                        onChange={(e) => setBookTitle(e.target.value)}
                      />
                    </Field>
                    <Field label={t('publisher')}>
                      <Input
                        value={bookPublisher}
                        onChange={(e) => setBookPublisher(e.target.value)}
                      />
                    </Field>
                    <Field label={t('isbn')}>
                      {/* Stored as typed. Alppy never resolves an ISBN against
                          anything, so normalising hyphens would be a rule with
                          no beneficiary and one more way to reject a correct
                          entry. */}
                      <Input
                        value={bookIsbn}
                        onChange={(e) => setBookIsbn(e.target.value)}
                        spellCheck={false}
                      />
                    </Field>
                    <Field label={t('sourceUrl')}>
                      <Input
                        value={bookUrl}
                        onChange={(e) => setBookUrl(e.target.value)}
                        spellCheck={false}
                      />
                    </Field>
                    <Field label={t('fileLabel')}>
                      {/* The upload's own name is provenance, not a title. */}
                      <LockedValue>{book.filename}</LockedValue>
                    </Field>
                    <div className="flex flex-wrap justify-end gap-3">
                      <Button variant="ghost" onClick={() => setEditingBook(null)}>
                        {tc('cancel')}
                      </Button>
                      <Button
                        variant="primary"
                        onClick={() => {
                          setError(null);
                          updateSource.mutate(
                            {
                              sourceId: book.id,
                              body: {
                                title: bookTitle,
                                publisher: bookPublisher,
                                isbn: bookIsbn,
                                url: bookUrl,
                              },
                            },
                            { onSuccess: () => setEditingBook(null), onError: report },
                          );
                        }}
                      >
                        {tc('save')}
                      </Button>
                    </div>
                  </>
                ) : (
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="min-w-0 flex-1 truncate font-semibold">
                      {book.title ?? (
                        <span className="text-ink-500">{t('noTitle')}</span>
                      )}
                    </span>
                    <span className="truncate font-mono text-label text-ink-500">
                      {book.filename}
                    </span>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setEditingBook(book.id);
                        setBookTitle(book.title ?? '');
                        setBookPublisher(book.publisher ?? '');
                        setBookIsbn(book.isbn ?? '');
                        setBookUrl(book.url ?? '');
                      }}
                    >
                      {t('rename')}
                    </Button>
                    <Button variant="ghost" onClick={() => setDeletingBook(book)}>
                      {tc('delete')}
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>

        {error ? (
          <p role="alert" className="text-body-s text-danger-600">
            {error}
          </p>
        ) : null}
      </div>

      <ConfirmDestructive
        open={deletingTheme !== null}
        onOpenChange={(open) => !open && setDeletingTheme(null)}
        title={t('deleteTheme', { name: deletingTheme ? label(deletingTheme) : '' })}
        description={t('deleteThemeBody')}
        cancelLabel={tc('cancel')}
        confirmLabel={tc('delete')}
        closeLabel={tc('close')}
        pending={removeChapter.isPending}
        error={error}
        onConfirm={() => {
          if (!deletingTheme) return;
          setError(null);
          removeChapter.mutate(
            { chapterId: deletingTheme.id, subjectId: subjectId as Uuid },
            { onSuccess: () => setDeletingTheme(null), onError: report },
          );
        }}
      />

      <ConfirmDestructive
        open={deletingBook !== null}
        onOpenChange={(open) => !open && setDeletingBook(null)}
        title={t('deleteTextbook', {
          name: deletingBook?.title ?? deletingBook?.filename ?? '',
        })}
        description={t('deleteTextbookBody')}
        cancelLabel={tc('cancel')}
        confirmLabel={tc('delete')}
        closeLabel={tc('close')}
        pending={removeSource.isPending}
        error={error}
        onConfirm={() => {
          if (!deletingBook) return;
          setError(null);
          removeSource.mutate(
            { sourceId: deletingBook.id },
            { onSuccess: () => setDeletingBook(null), onError: report },
          );
        }}
      />
    </div>
  );
}
