'use client';

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  IlloTray,
  LoadingState,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';

import { Link } from '@/i18n/navigation';
import { useScans, useSheets } from '@/lib/api/queries';
import { useFormatters } from '@/lib/format';
import { useScope } from '@/lib/scope';

/**
 * The piles of copies the teacher has uploaded.
 *
 * This route did not exist. `GET /scans` shipped, the nav's "Corrections" went
 * straight to `/scans/new`, and the home screen's "N corrections pending" was
 * plain text — so a teacher who uploaded a pile, closed the tab and came back
 * had no way to reach the review again. The overview counted work it could not
 * lead to.
 */
const PENDING = new Set(['uploaded', 'processing', 'needs_review']);

export default function ScansIndexPage() {
  const t = useTranslations('scans');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const fmt = useFormatters();
  const { classId, subjectId } = useScope();

  const { data, isLoading, isError, refetch } = useScans();
  // Scans carry a sheet, and a sheet carries a class AND a Branch; scoping the
  // list means resolving that hop here.
  //
  // Narrowed by Branch too since D75: a teacher who takes maths and French in
  // 7B was shown one queue holding both, mixed with whatever a co-teacher had
  // scanned. `useSheets` already keys its cache by both, so this costs a
  // parameter rather than a request.
  const sheets = useSheets(classId ?? undefined, subjectId ?? undefined);

  if (isLoading) return <LoadingState shape="list" label={tc('loading')} rows={4} />;
  if (isError) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={<Button onClick={() => void refetch()}>{tc('retry')}</Button>}
      />
    );
  }

  const sheetTitles = new Map((sheets.data ?? []).map((s) => [s.id, s.title]));
  const scans = (data ?? []).filter(
    // An unattached pile (no sheet yet) still belongs to whoever uploaded it,
    // so it stays listed rather than being filtered into invisibility. It has
    // no Branch to be narrowed by either — that is why the API leaves it with
    // its uploader, and why it must not disappear when a Branch is selected.
    (scan) => scan.sheet_id === null || sheetTitles.has(scan.sheet_id),
  );

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          {/* Not "all": the list is scoped to the class and, since D75, to the
              Branches this teacher takes. A heading that claims otherwise
              turns a correct filter into an apparent bug. */}
          <h1>{t('scopedScans')}</h1>
          <p className="text-body-s text-ink-500">{t('scopedScansHint')}</p>
        </div>
        <Link href="/scans/new" className="ard-btn" data-variant="primary">
          {t('newScan')}
        </Link>
      </div>

      {scans.length === 0 ? (
        <EmptyState
          illustration={<IlloTray />}
          title={t('emptyTitle')}
          description={t('noScans')}
          action={
            <Link href="/scans/new" className="ard-btn" data-variant="primary">
              {t('newScan')}
            </Link>
          }
        />
      ) : (
        <ul className="flex list-none flex-col gap-3 p-0">
          {scans.map((scan) => (
            <li key={scan.id}>
              <Card>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <Link href={`/scans/${scan.id}`} className="font-bold">
                      {scan.sheet_id
                        ? (sheetTitles.get(scan.sheet_id) ?? scan.original_filename)
                        : scan.original_filename}
                    </Link>
                    <p className="text-body-s text-ink-500">
                      {[
                        t('pagesCount', { count: scan.pages.length }),
                        fmt.date(scan.created_at),
                      ].join(' · ')}
                    </p>
                  </div>
                  <Badge variant={PENDING.has(scan.status) ? 'warn' : 'success'}>
                    {t(`status.${scan.status}`)}
                  </Badge>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
