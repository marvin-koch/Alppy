'use client';

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  IconChevronRight,
  IconSearch,
  IconSheet,
  IlloSheet,
  Input,
  LoadingState,
  Card,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import { Link } from '@/i18n/navigation';
import { useSheets } from '@/lib/api/queries';
import type { SheetOut } from '@/lib/api/types';
import { useScope } from '@/lib/scope';
import { useFormatters } from '@/lib/format';

/**
 * The sheets the teacher has built, for the class the shell is on.
 *
 * Grouped by what is left to do rather than listed flat. A sheet is either
 * still a draft — created, PDFs not made — or ready for the photocopier, and
 * those are two different piles on a teacher's desk. Each group is one card
 * with a divided list inside: a card per sheet made twelve identical objects
 * compete for attention and said nothing about which one needed work.
 */
export default function SheetsIndexPage() {
  const t = useTranslations('sheets');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const { classId, currentClass } = useScope();
  const { data, isLoading, isError, refetch } = useSheets(classId ?? undefined);
  const [search, setSearch] = useState('');

  const sheets = useMemo(() => data ?? [], [data]);
  const needle = search.trim().toLowerCase();
  const visible = useMemo(
    () =>
      needle ? sheets.filter((sheet) => sheet.title.toLowerCase().includes(needle)) : sheets,
    [sheets, needle],
  );
  const drafts = visible.filter((sheet) => !sheet.rendered_at);
  const ready = visible.filter((sheet) => Boolean(sheet.rendered_at));

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1>{t('title')}</h1>
          {currentClass ? (
            <p className="mt-1 text-body-s text-ink-500">
              {t('forClass', { code: currentClass.code })}
            </p>
          ) : null}
        </div>
        <Link href="/sheets/new" className="ard-btn" data-variant="primary">
          {t('new')}
        </Link>
      </header>

      {isLoading ? (
        <LoadingState shape="list" label={tc('loading')} rows={4} />
      ) : isError ? (
        <ErrorState
          title={te('title')}
          description={te('body')}
          action={<Button onClick={() => void refetch()}>{tc('retry')}</Button>}
        />
      ) : sheets.length === 0 ? (
        <Card>
          <EmptyState
            illustration={<IlloSheet />}
            title={t('empty.title')}
            description={t('empty.body')}
            action={
              <Link href="/sheets/new" className="ard-btn" data-variant="primary">
                {t('empty.action')}
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="flex flex-col gap-6">
          {/* A search box only once there is something to search: with four
              sheets it is furniture. */}
          {sheets.length > 6 ? (
            <Input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t('searchPlaceholder')}
              aria-label={t('searchPlaceholder')}
              leadingIcon={<IconSearch size={18} />}
            />
          ) : null}

          {visible.length === 0 ? (
            <EmptyState title={t('noMatches')} size="sm" />
          ) : null}

          {drafts.length > 0 ? (
            <SheetGroup
              title={t('groups.drafts')}
              hint={t('groups.draftsHint')}
              sheets={drafts}
              state="draft"
            />
          ) : null}
          {ready.length > 0 ? (
            <SheetGroup title={t('groups.ready')} sheets={ready} state="ready" />
          ) : null}
        </div>
      )}
    </div>
  );
}

function SheetGroup({
  title,
  hint,
  sheets,
  state,
}: {
  title: string;
  hint?: string;
  sheets: SheetOut[];
  state: 'draft' | 'ready';
}) {
  const t = useTranslations('sheets');
  const fmt = useFormatters();

  return (
    <section aria-labelledby={`sheets-${state}`}>
      <div className="mb-2 flex items-baseline justify-between gap-3 px-1">
        <h2 id={`sheets-${state}`} className="text-h3">
          {title}
          <span className="ml-2 font-sans text-body-s font-normal text-ink-500" data-numeric>
            {sheets.length}
          </span>
        </h2>
        {hint ? <p className="text-body-s text-ink-500">{hint}</p> : null}
      </div>
      <Card flush>
        <ul className="m-0 list-none divide-y divide-line p-0">
          {sheets.map((sheet) => {
            const pages = sheet.instances[0]?.page_count ?? null;
            const adaptive = sheet.target !== 'class' || sheet.derived_from_id !== null;
            return (
              <li key={sheet.id}>
                <Link
                  href={`/sheets/${sheet.id}`}
                  className="flex min-h-[4.5rem] items-center gap-4 px-4 py-3 text-ink-900 no-underline transition-colors hover:bg-primary-050 focus-visible:bg-primary-050 sm:px-5"
                >
                  {/* State carried three ways: tint, the glyph's colour, and
                      the group heading it sits under. */}
                  <span
                    aria-hidden
                    className={
                      state === 'ready'
                        ? 'inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-success-100 text-success-600'
                        : 'inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-surface-2 text-ink-500'
                    }
                  >
                    <IconSheet size={22} />
                  </span>
                  <span className="min-w-0 flex-grow">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="truncate font-display text-body-l font-semibold">
                        {sheet.title.trim() || t('untitled')}
                      </span>
                      {adaptive ? <Badge variant="info">{t('adaptiveTag')}</Badge> : null}
                    </span>
                    <span className="block text-body-s text-ink-500">
                      {[
                        t('itemCount', { count: sheet.items.length }),
                        pages ? t('pageCount', { count: pages }) : null,
                        sheet.language.toUpperCase(),
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                  </span>
                  <span className="hidden shrink-0 text-body-s text-ink-500 sm:block">
                    {fmt.relativeDays(sheet.rendered_at ?? sheet.created_at)}
                  </span>
                  <IconChevronRight size={20} className="shrink-0 text-ink-300" aria-hidden />
                </Link>
              </li>
            );
          })}
        </ul>
      </Card>
    </section>
  );
}
