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
import { useLocale, useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import { Link } from '@/i18n/navigation';
import { useCurriculumTree, useSheets } from '@/lib/api/queries';
import type { SheetOut, Uuid } from '@/lib/api/types';
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
  const { classId, currentClass, subjectId } = useScope();
  const locale = useLocale();
  // Only for the Theme headings and their order — the sheets themselves come
  // from `useSheets`, so a tree that has not arrived yet delays the grouping,
  // never the list.
  const tree = useCurriculumTree(classId, subjectId ? { subjectId } : {});
  // Until it lands there is no Theme order, and grouping against an empty one
  // would put every sheet under "Non classé" for a frame. Wait instead.
  const isLoadingTree = tree.isLoading;
  // Scoped to the Branch, not just the class. The Theme headings come from ONE
  // branch's tree, so listing every subject's sheets against it would file
  // another subject's work under "Non classé" permanently — not a loading
  // flash, the resting state.
  const { data, isLoading, isError, refetch } = useSheets(
    classId ?? undefined,
    subjectId ?? undefined,
  );
  const [search, setSearch] = useState('');

  const sheets = useMemo(() => data ?? [], [data]);

  /**
   * The Themes of this Branch, in the order the tree gives them, each with the
   * label to head its section. Sheets whose `chapter_id` matches none of these
   * are in the `unfiled` bucket — the tree deliberately omits that chapter, so
   * "not in this list" IS the test, and no key comparison is needed.
   */
  const themeOrder = useMemo(() => {
    const out: Array<{ id: Uuid; label: string }> = [];
    // Every branch the tree returned, not just the scoped one: the list is
    // already narrowed by `subjectId`, and reading them all means a sheet can
    // never fall through to "unfiled" merely because the branch was missed.
    const competences = (tree.data?.branches ?? []).flatMap((b) => b.competences);
    for (const competence of competences) {
      for (const theme of competence.themes) {
        out.push({
          id: theme.chapter_id,
          label: theme.labels?.[locale] ?? theme.labels?.fr ?? theme.key,
        });
      }
    }
    return out;
  }, [tree.data, locale]);
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

      {isLoading || isLoadingTree ? (
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
              themes={themeOrder}
            />
          ) : null}
          {ready.length > 0 ? (
            <SheetGroup
              title={t('groups.ready')}
              sheets={ready}
              state="ready"
              themes={themeOrder}
            />
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
  themes,
}: {
  title: string;
  hint?: string;
  sheets: SheetOut[];
  state: 'draft' | 'ready';
  themes: Array<{ id: Uuid; label: string }>;
}) {
  const t = useTranslations('sheets');

  // Themes in the tree's order, then everything left over — which is exactly
  // the `unfiled` bucket, since the tree omits that chapter. Empty Themes are
  // dropped: a heading with nothing under it is noise on this screen, and the
  // tree is where the full programme is on show.
  const byTheme = new Map<Uuid, SheetOut[]>();
  for (const sheet of sheets) {
    const bucket = byTheme.get(sheet.chapter_id);
    if (bucket) bucket.push(sheet);
    else byTheme.set(sheet.chapter_id, [sheet]);
  }
  const known = new Set(themes.map((theme) => theme.id));
  const sections = themes
    .filter((theme) => byTheme.has(theme.id))
    .map((theme) => ({ key: theme.id, label: theme.label, sheets: byTheme.get(theme.id) ?? [] }));
  const unfiled = sheets.filter((sheet) => !known.has(sheet.chapter_id));

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
      <div className="flex flex-col gap-3">
        {sections.map((section) => (
          <ThemeSection
            key={section.key}
            heading={section.label}
            sheets={section.sheets}
            state={state}
          />
        ))}
        {unfiled.length > 0 ? (
          <ThemeSection
            key="unfiled"
            heading={t('unfiledTheme')}
            hint={t('unfiledThemeHelp')}
            sheets={unfiled}
            state={state}
          />
        ) : null}
      </div>
    </section>
  );
}

function ThemeSection({
  heading,
  hint,
  sheets,
  state,
}: {
  heading: string;
  hint?: string;
  sheets: SheetOut[];
  state: 'draft' | 'ready';
}) {
  const t = useTranslations('sheets');
  const fmt = useFormatters();

  // Within a Theme, the common sheet comes before the sheets that answer it —
  // that is the order a teaching unit actually happens in.
  const personalised = (sheet: SheetOut) =>
    sheet.target !== 'class' || sheet.derived_from_id !== null;
  const ordered = [...sheets.filter((s) => !personalised(s)), ...sheets.filter(personalised)];
  const firstPersonalised = ordered.findIndex(personalised);

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-3 px-1">
        <h3 className="text-body-s font-bold text-ink-700">{heading}</h3>
        {hint ? <p className="max-w-md text-label text-ink-500">{hint}</p> : null}
      </div>
      <Card flush>
        <ul className="m-0 list-none divide-y divide-line p-0">
          {ordered.map((sheet, index) => {
            const pages = sheet.instances[0]?.page_count ?? null;
            const adaptive = personalised(sheet);
            return (
              <li key={sheet.id}>
                {index === firstPersonalised && firstPersonalised > 0 ? (
                  <p className="bg-surface-2 px-4 py-1 text-label text-ink-500 sm:px-5">
                    {t('groupPersonalized')}
                  </p>
                ) : null}
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
    </div>
  );
}
