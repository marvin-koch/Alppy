'use client';

import {
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  IconBook,
  IconCheck,
  IconClock,
  IconPrint,
  IconScan,
  IconSheet,
  IlloClock,
  Input,
  LoadingState,
  Panel,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import { Link } from '@/i18n/navigation';
import { useFormatters } from '@/lib/format';
import { useScope } from '@/lib/scope';
import { useTimeline } from '@/lib/api/queries';
import type { EventKind, TimelineEventOut } from '@/lib/api/types';
import { requestIdOf } from '@/lib/api/error-message';

const PAGE = 20;

/** Every kind, in the order a teaching cycle actually runs. */
const KINDS: EventKind[] = [
  'source_imported',
  'chapter_read',
  'sheet_created',
  'sheet_rendered',
  'sheet_printed',
  'scan_uploaded',
  'scan_confirmed',
  'adaptive_proposed',
  'adaptive_exported',
  'feedback_written',
  'feedback_approved',
];

/**
 * One pictogram per kind. Drawn in the repo, never an icon library, and the
 * icon is never the only thing carrying the meaning — the kind is also spelled
 * out in words beside it.
 */
function kindIcon(kind: EventKind) {
  switch (kind) {
    case 'source_imported':
    case 'chapter_read':
      return <IconBook />;
    case 'sheet_created':
    case 'sheet_rendered':
    case 'adaptive_proposed':
    case 'adaptive_exported':
      return <IconSheet />;
    case 'sheet_printed':
      return <IconPrint />;
    case 'scan_uploaded':
      return <IconScan />;
    case 'scan_confirmed':
    case 'feedback_approved':
      return <IconCheck />;
    default:
      return <IconClock />;
  }
}

/** Where clicking an entry goes, when the thing it describes still exists. */
function hrefFor(event: TimelineEventOut): string | null {
  if (!event.resolved) return null;
  switch (event.subject_type) {
    case 'sheet':
      return `/sheets/${event.subject_id}`;
    case 'scan':
      return `/scans/${event.subject_id}`;
    case 'source':
      return '/sources';
    default:
      return null;
  }
}

export default function TimelinePage() {
  const t = useTranslations('timeline');
  const tc = useTranslations('common');
  const fmt = useFormatters();
  const scope = useScope();

  const [kinds, setKinds] = useState<EventKind[]>([]);
  const [search, setSearch] = useState('');
  const [limit, setLimit] = useState(PAGE);

  const timeline = useTimeline({
    kind: kinds.length ? kinds : undefined,
    subject_id: scope.subjectId ?? undefined,
    q: search || undefined,
    limit,
  });

  const items = timeline.data?.items ?? [];
  const facets = timeline.data?.facets.by_kind ?? {};

  /**
   * Grouped by day, because that is the unit a teacher thinks in — "what did I
   * do on Tuesday", never "show me entries 20 to 40". The order the server
   * returned is preserved; this only inserts the headings.
   */
  const days = useMemo(() => {
    const out: { key: string; label: string; entries: TimelineEventOut[] }[] = [];
    for (const event of items) {
      const key = fmt.date(event.occurred_at);
      const last = out[out.length - 1];
      if (last && last.key === key) last.entries.push(event);
      else out.push({ key, label: key, entries: [event] });
    }
    return out;
  }, [items, fmt]);

  const toggle = (kind: EventKind) =>
    setKinds((current) =>
      current.includes(kind) ? current.filter((k) => k !== kind) : [...current, kind],
    );

  if (timeline.isError) {
    return (
      <ErrorState
        title={t('error.title')}
        description={t('error.body')}
        requestId={requestIdOf(timeline.error)}
        action={
          <Button variant="primary" onClick={() => void timeline.refetch()}>
            {tc('retry')}
          </Button>
        }
      />
    );
  }

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6">
        <h1>{t('title')}</h1>
        <p className="text-ink-500">{t('subtitle')}</p>
      </header>

      <Card className="mb-6">
        <label className="block">
          <span className="text-label uppercase tracking-label text-ink-500">{t('search')}</span>
          <Input
            className="mt-2"
            value={search}
            placeholder={t('searchPlaceholder')}
            onChange={(event) => {
              setSearch(event.target.value);
              setLimit(PAGE);
            }}
          />
        </label>

        {/* A chip reports what selecting it would give, not what is already
            selected: the server computes each facet with every filter EXCEPT
            its own. A chip whose count is zero is not offered at all. */}
        <ul className="mt-4 flex list-none flex-wrap gap-2 p-0">
          <li>
            <button
              type="button"
              className="ard-chip min-h-11"
              data-variant={kinds.length === 0 ? 'primary' : 'neutral'}
              aria-pressed={kinds.length === 0}
              onClick={() => setKinds([])}
            >
              {t('all')}
            </button>
          </li>
          {KINDS.filter((kind) => (facets[kind] ?? 0) > 0).map((kind) => (
            <li key={kind}>
              <button
                type="button"
                className="ard-chip min-h-11"
                data-variant={kinds.includes(kind) ? 'primary' : 'neutral'}
                aria-pressed={kinds.includes(kind)}
                onClick={() => {
                  toggle(kind);
                  setLimit(PAGE);
                }}
              >
                {t(`kind.${kind}`)} · {facets[kind]}
              </button>
            </li>
          ))}
        </ul>
      </Card>

      {timeline.isLoading ? (
        <LoadingState shape="timeline" label={tc('loading')} rows={9} />
      ) : items.length === 0 ? (
        <EmptyState
          illustration={<IlloClock />}
          title={t('empty.title')}
          description={t('empty.body')}
        />
      ) : (
        <>
          <p className="mb-3 text-body-s text-ink-500" role="status">
            {t('count', { count: timeline.data?.total ?? 0 })}
          </p>

          <ol className="flex list-none flex-col gap-6 p-0">
            {days.map((day) => (
              <li key={day.key}>
                <h2 className="mb-3 text-h3">{day.label}</h2>
                <ol className="flex list-none flex-col gap-2 border-l border-line p-0 pl-4">
                  {day.entries.map((event) => {
                    const href = hrefFor(event);
                    const body = (
                      <Panel className="flex flex-wrap items-center gap-3">
                        <span aria-hidden className="text-ink-500">
                          {kindIcon(event.kind)}
                        </span>
                        <span className="flex-1">
                          {/* The kind in words, always — the pictogram alone
                              would leave the line meaningless in greyscale or
                              to a screen reader. */}
                          <span className="block text-body-s text-ink-500">
                            {t(`kind.${event.kind}`)}
                          </span>
                          <span className="block font-bold">{event.title}</span>
                        </span>
                        {event.class_code ? <Chip data-numeric>{event.class_code}</Chip> : null}
                        {/* The row it describes is gone. The line stays —
                            deleting a sheet does not un-print it — but it is
                            no longer a link. */}
                        {event.resolved ? null : <Chip>{t('deleted')}</Chip>}
                        <time
                          dateTime={event.occurred_at}
                          className="text-body-s text-ink-500 tabular-nums"
                        >
                          {fmt.dateTime(event.occurred_at).split(', ')[1] ?? ''}
                        </time>
                      </Panel>
                    );
                    return (
                      <li key={event.id}>
                        {href ? (
                          <Link href={href} className="block no-underline">
                            {body}
                          </Link>
                        ) : (
                          body
                        )}
                      </li>
                    );
                  })}
                </ol>
              </li>
            ))}
          </ol>

          {(timeline.data?.total ?? 0) > items.length ? (
            <div className="mt-6 flex justify-center">
              <Button onClick={() => setLimit((current) => current + PAGE)}>{t('loadMore')}</Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
