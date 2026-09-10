'use client';

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  IconBook,
  IconChevronLeft,
  IconChevronRight,
  IconSearch,
  IlloCompass,
  Input,
  LoadingState,
  Select,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useEffect, useMemo, useState } from 'react';

import { Link } from '@/i18n/navigation';
import { DEFAULT_PAGE_SIZE, useSourceExercises } from '@/lib/api/queries';
import { apiErrorMessage } from '@/lib/api/error-message';
import type {
  ExerciseOut,
  ExerciseType,
  SourceOut,
  SourceSectionOut,
  Uuid,
} from '@/lib/api/types';
import { ExerciseRow } from './ExerciseRow';
import type { DraftSheet } from './useDraftSheet';

interface Props {
  sourceId: Uuid | null;
  section: SourceSectionOut | null;
  draft: DraftSheet;
  /** The indexed documents, offered as the first step when none is open. */
  sources: SourceOut[];
  onChooseSource: (id: Uuid) => void;
  /**
   * The Theme chosen in `ThemePicker`, or `'none'` for the untagged bucket.
   * Undefined leaves the list unfiltered by theme.
   */
  themeFilter?: Uuid | 'none';
}

/**
 * The document side of the builder: everything the chosen chapter holds.
 *
 * Two properties this component exists to keep.
 *
 * **Nothing is unreachable.** This used to be guaranteed by NOT filtering on
 * the curriculum theme at all: `Exercise.chapter_id` is inferred, it is null
 * on a large minority of a real textbook's rows, and a filter on it hid those
 * exercises without saying so.
 *
 * Since D59 the Theme IS the builder's root, so the same property has to be
 * kept by design rather than by omission: `ThemePicker` pins a counted
 * "Sans thème" row at the root of its tree, always rendered, and choosing it
 * sends `chapter_id=none` — which is why the sentinel exists and why it is
 * distinct from the parameter simply being absent. If that row is ever
 * removed, or hidden when its count is zero, untagged exercises silently
 * become unreachable again.
 *
 * **Ticks survive filter changes.** The selection lives in `draft`, never in
 * this list. A teacher who ticks three exercises, searches for a fourth, and
 * finds the first three gone has lost work.
 */
export function ExercisePicker({
  sourceId,
  section,
  draft,
  sources,
  onChooseSource,
  themeFilter,
}: Props) {
  const t = useTranslations('builder');
  const tc = useTranslations('common');
  const tx = useTranslations('exercise');
  const te = useTranslations('errors.code');

  const [type, setType] = useState<ExerciseType | ''>('');
  const [difficulty, setDifficulty] = useState<number | ''>('');
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [offset, setOffset] = useState(0);

  // Typing must not fire a request per keystroke against a thousand rows.
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Any filter change invalidates the page number: staying on page 4 of a
  // result set that now has one page shows an empty list and no explanation.
  useEffect(() => {
    setOffset(0);
  }, [type, difficulty, debounced, section?.id, themeFilter]);

  const query = useMemo(
    () => ({
      ...(section ? { section_id: section.id } : {}),
      ...(themeFilter ? { chapter_id: themeFilter } : {}),
      ...(type ? { type } : {}),
      ...(difficulty ? { difficulty } : {}),
      ...(debounced ? { q: debounced } : {}),
      offset,
      limit: DEFAULT_PAGE_SIZE,
    }),
    [section, themeFilter, type, difficulty, debounced, offset],
  );

  const exercises = useSourceExercises(sourceId, query);
  const data = exercises.data;
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const facets = data?.facets;

  const hasFilters = Boolean(type || difficulty || debounced);

  if (!sourceId) {
    return <DocumentChooser sources={sources} onChoose={onChooseSource} />;
  }

  // Group a page by the book's page number, so the teacher can check it against
  // the paper on their desk without reading every statement.
  const groups: { page: number | null; rows: ExerciseOut[] }[] = [];
  for (const row of items) {
    const last = groups.at(-1);
    if (last && last.page === row.source_page) last.rows.push(row);
    else groups.push({ page: row.source_page, rows: [row] });
  }

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-h3">{t('inDocument')}</h2>
        {facets ? <Badge variant="neutral">{t('exerciseCount', { count: facets.total })}</Badge> : null}
      </div>

      {/* — filters — */}
      <div className="grid grid-cols-1 gap-2">
        <label className="relative flex items-center">
          <span className="sr-only">{t('searchPlaceholder')}</span>
          <IconSearch
            size={18}
            className="pointer-events-none absolute left-3 text-ink-500"
            aria-hidden
          />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('searchPlaceholder')}
            className="pl-10"
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <TypeChip
          label={t('filterAll')}
          count={facets?.total}
          active={type === ''}
          onClick={() => setType('')}
        />
        {(['mcq', 'true_false', 'open'] as const).map((kind) => (
          <TypeChip
            key={kind}
            label={tx(`type.${kind}`)}
            count={
              facets
                ? kind === 'mcq'
                  ? facets.mcq
                  : kind === 'true_false'
                    ? facets.true_false
                    : facets.open
                : undefined
            }
            active={type === kind}
            onClick={() => setType(type === kind ? '' : kind)}
          />
        ))}
        <Select
          aria-label={t('anyDifficulty')}
          value={difficulty}
          onChange={(e) =>
            setDifficulty(e.currentTarget.value ? Number(e.currentTarget.value) : '')
          }
          className="ml-auto w-auto min-w-40"
        >
          <option value="">{t('anyDifficulty')}</option>
          {[1, 2, 3, 4, 5].map((level) => (
            <option key={level} value={level}>
              {t('difficultyLevel', { level })}
            </option>
          ))}
        </Select>
      </div>

      {/* The count that reassures a teacher their ticks survived the filter. */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
        <span className="text-body-s text-ink-500">
          {total > 0
            ? t('showingRange', {
                from: offset + 1,
                to: Math.min(offset + items.length, total),
                total,
              })
            : null}
        </span>
        <Badge variant={draft.count > 0 ? 'primary' : 'neutral'}>
          {t('selectedTotal', { count: draft.count })}
        </Badge>
      </div>

      {exercises.isError ? (
        <ErrorState
          title={te('generic')}
          description={apiErrorMessage(exercises.error, te)}
          action={<Button onClick={() => void exercises.refetch()}>{tc('retry')}</Button>}
        />
      ) : exercises.isPending ? (
        <LoadingState shape="list" label={tc('loading')} rows={5} />
      ) : items.length === 0 ? (
        <EmptyState
          title={t('noMatches')}
          description={hasFilters ? undefined : t('emptyPickBody')}
          {...(hasFilters
            ? {
                action: (
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setType('');
                      setDifficulty('');
                      setSearch('');
                    }}
                  >
                    {t('clearFilters')}
                  </Button>
                ),
              }
            : {})}
        />
      ) : (
        <div className="flex flex-col gap-4">
          {groups.map((group) => {
            const kept = group.rows.filter((row) => draft.has(row.id)).length;
            return (
              <div key={group.page ?? 'none'} className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-label text-ink-500">
                    {group.page ? t('pageLabel', { page: group.page }) : t('inDocument')}
                  </span>
                  <span className="h-px flex-grow bg-line" />
                  <span className="text-body-s text-ink-500">
                    {t('keptOfPage', { kept, total: group.rows.length })}
                  </span>
                </div>
                {group.rows.map((row) => (
                  <ExerciseRow
                    key={row.id}
                    exercise={row}
                    checked={draft.has(row.id)}
                    disabled={!draft.has(row.id) && draft.isFull}
                    onToggle={() => draft.toggle(row)}
                  />
                ))}
              </div>
            );
          })}
        </div>
      )}

      {total > DEFAULT_PAGE_SIZE ? (
        <div className="flex items-center justify-between gap-3 border-t border-line pt-3">
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={<IconChevronLeft />}
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - DEFAULT_PAGE_SIZE))}
          >
            {t('previous')}
          </Button>
          <span className="mono text-body-s text-ink-500" data-numeric>
            {t('showingRange', {
              from: offset + 1,
              to: Math.min(offset + items.length, total),
              total,
            })}
          </span>
          <Button
            variant="secondary"
            size="sm"
            trailingIcon={<IconChevronRight />}
            disabled={offset + DEFAULT_PAGE_SIZE >= total}
            onClick={() => setOffset(offset + DEFAULT_PAGE_SIZE)}
          >
            {t('next')}
          </Button>
        </div>
      ) : null}
    </Card>
  );
}

function TypeChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number | undefined;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className="min-h-11 cursor-pointer border-0 bg-transparent p-0"
    >
      <Badge variant={active ? 'primary' : 'neutral'}>
        {label}
        {count === undefined ? '' : ` · ${count}`}
      </Badge>
    </button>
  );
}

/**
 * The first step, when no document is open: the books themselves, as buttons.
 *
 * A select in a toolbar is the right control once a document is open and the
 * teacher wants another; it is the wrong one for the first choice, where the
 * page otherwise showed an illustration and told them to look "above".
 */
function DocumentChooser({
  sources,
  onChoose,
}: {
  sources: SourceOut[];
  onChoose: (id: Uuid) => void;
}) {
  const t = useTranslations('builder');

  if (sources.length === 0) {
    return (
      <Card>
        <EmptyState
          illustration={<IlloCompass />}
          title={t('noDocumentsTitle')}
          description={t('noDocumentsBody')}
          action={
            <Link href="/sources" className="ard-btn" data-variant="primary">
              {t('importDocument')}
            </Link>
          }
        />
      </Card>
    );
  }

  return (
    <Card className="flex flex-col gap-3">
      <div>
        <h2 className="text-h3">{t('emptyPickTitle')}</h2>
        <p className="mt-1 text-body-s text-ink-500">{t('emptyPickBody')}</p>
      </div>
      <ul className="flex list-none flex-col gap-2 p-0">
        {sources.map((source) => (
          <li key={source.id}>
            <button
              type="button"
              onClick={() => onChoose(source.id)}
              className="flex min-h-11 w-full cursor-pointer items-center gap-3.5 rounded-md border-2 border-line bg-surface p-3 text-left transition-colors hover:border-primary-500 hover:bg-primary-050"
            >
              <span
                className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-primary-100 text-primary-700"
                aria-hidden
              >
                <IconBook size={22} />
              </span>
              <span className="min-w-0 flex-grow">
                <span className="block truncate font-display font-semibold text-ink-900">
                  {source.filename}
                </span>
                <span className="block text-body-s text-ink-500">
                  {[
                    t('sectionCount', { count: source.section_count }),
                    t('exerciseCount', { count: source.exercise_count }),
                  ].join(' · ')}
                </span>
              </span>
              <IconChevronRight size={20} className="shrink-0 text-ink-300" aria-hidden />
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
