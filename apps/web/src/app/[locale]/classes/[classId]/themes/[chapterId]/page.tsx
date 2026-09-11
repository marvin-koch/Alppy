'use client';

import {
  Breadcrumb,
  Card,
  ConceptTag,
  EmptyState,
  ErrorState,
  IconChevronRight,
  IlloCompass,
  LoadingState,
  MasteryBandTag,
  Panel,
  type MasteryBand,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { use } from 'react';

import { Link } from '@/i18n/navigation';
import { useBandLabels } from '@/lib/bands';
import { useClass, useCurriculumTree, useSheets } from '@/lib/api/queries';
import type { Uuid } from '@/lib/api/types';
import { useFormatters } from '@/lib/format';
import { useClassSubject } from '@/lib/use-class-subject';
import { isNotFound, requestIdOf } from '@/lib/api/error-message';
import { NotFoundState } from '@/components/NotFoundState';

/** One Theme, for one class: where it sits, what it credits, what was set. */
export default function ThemePage({
  params,
}: {
  params: Promise<{ classId: string; chapterId: string }>;
}) {
  const { classId, chapterId } = use(params);
  const t = useTranslations('curriculum');
  const tnav = useTranslations('nav');
  const tt = useTranslations('tree');
  const tm = useTranslations('mastery');
  const te = useTranslations('errors.generic');
  const a11y = useTranslations('a11y');
  const locale = useLocale();
  const fmt = useFormatters();
  const bandLabels = useBandLabels();

  const klass = useClass(classId as Uuid);
  const { subjectId } = useClassSubject(klass.data);

  const tree = useCurriculumTree(classId as Uuid, subjectId ? { subjectId } : {});
  const sheets = useSheets(classId as Uuid, subjectId);

  const branch = tree.data?.branches.find((b) => b.subject_id === subjectId) ?? null;
  const parent =
    branch?.competences.find((c) => c.themes.some((th) => th.chapter_id === chapterId)) ?? null;
  const theme = parent?.themes.find((th) => th.chapter_id === chapterId) ?? null;

  const label = (labels: Record<string, string> | undefined, fallback: string) =>
    labels?.[locale] ?? labels?.fr ?? fallback;

  // Sheets FILED here (`Sheet.chapter_id`), never sheets whose items happen to
  // touch this Theme. The filing is the teacher's own statement (I-sheets-11).
  const filed = (sheets.data ?? []).filter((s) => s.chapter_id === chapterId);

  const crumbs = [
    { label: klass.data?.code ?? '', href: `/classes/${classId}`, key: 'class' },
    ...(branch
      ? [
          {
            label: label(branch.labels, branch.subject_key),
            href: `/classes/${classId}`,
            key: 'branch',
          },
        ]
      : []),
    ...(parent
      ? [
          {
            label: parent.code,
            href: `/classes/${classId}/competences/${parent.competency_id}`,
            key: 'competence',
          },
        ]
      : []),
    { label: theme ? label(theme.labels, theme.key) : '', key: 'theme' },
  ];

  const header = (
    <Breadcrumb
      className="mb-2"
      label={a11y('breadcrumb')}
      items={crumbs}
      renderLink={(item, children) => <Link href={item.href!}>{children}</Link>}
    />
  );

  if (tree.isLoading) {
    return (
      <div className="mx-auto max-w-4xl">
        {header}
        <LoadingState shape="profile" label={a11y('loading')} />
      </div>
    );
  }

  if (tree.isError) {
    // A stale bookmark, a link from a colleague, an id that stopped being
    // this teacher's: a 404 is an answer, and "réessayez" re-asks it (G26).
    if (isNotFound(tree.error)) {
      return <NotFoundState backHref={`/classes/${classId}`} backLabel={tnav('classes')} />;
    }
    return (
      <div className="mx-auto max-w-4xl">
        {header}
        <ErrorState
          title={te('title')}
          description={te('body')}
          requestId={requestIdOf(tree.error)}
        />
      </div>
    );
  }

  if (!theme || !parent) {
    return (
      <div className="mx-auto max-w-4xl">
        {header}
        <EmptyState
          illustration={<IlloCompass />}
          title={t('themeMissing.title')}
          description={t('themeMissing.body')}
        />
      </div>
    );
  }

  const { assessed_count: assessed, child_count: total } = theme.mastery;

  return (
    <div className="mx-auto max-w-4xl">
      {header}

      <header className="mb-6 flex flex-col gap-3">
        <h1>{label(theme.labels, theme.key)}</h1>
        <div className="flex flex-wrap items-center gap-3">
          <MasteryBandTag
            band={theme.mastery.band as MasteryBand}
            label={bandLabels[theme.mastery.band as MasteryBand]}
            caption={
              total > 0 && assessed < total ? tm('coverage', { assessed, total }) : undefined
            }
          />
          <span className="text-body-s text-ink-500">
            {tt('sheetCount', { count: filed.length })}
          </span>
        </div>
      </header>

      {/* Where it SITS versus what it CREDITS — one Competence, many codes.
          The distinction is the whole of D56, and this is the only screen a
          teacher can see it on. */}
      <Panel className="mb-4 flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-label uppercase text-ink-500">{t('sitsUnder')}</span>
          <Link href={`/classes/${classId}/competences/${parent.competency_id}`}>
            {label(parent.labels, parent.code)}
          </Link>
          <ConceptTag code={parent.code} />
        </div>
        {theme.competency_ids.length > 1 ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-label uppercase text-ink-500">{t('credits')}</span>
            {theme.competency_ids.map((id) => {
              const c = branch?.competences.find((x) => x.competency_id === id);
              return <ConceptTag key={id} code={c?.code ?? id.slice(0, 8)} />;
            })}
          </div>
        ) : null}
        <p className="text-body-s text-ink-500">{t('creditsHelp')}</p>
      </Panel>

      <Card>
        <h2 className="mb-3 text-h3">{t('sheetsFiled')}</h2>
        {filed.length === 0 ? (
          <p className="text-body-s text-ink-500">{t('noSheetsFiled')}</p>
        ) : (
          <ul className="flex list-none flex-col gap-1 p-0">
            {filed.map((sheet) => (
              <li key={sheet.id}>
                <Link
                  href={`/sheets/${sheet.id}`}
                  className="flex min-h-11 flex-wrap items-center gap-3 rounded-md px-2 py-2 no-underline hover:bg-primary-050"
                >
                  <span className="min-w-0 flex-1 font-semibold text-ink-900">{sheet.title}</span>
                  {/* A corrected sheet IS its confirmed scan; there is no
                      separate entity, so the count of piles is the honest
                      thing to show here. */}
                  <span className="text-body-s text-ink-500">
                    {sheet.scans.some((s) => s.confirmed_at)
                      ? t('state.corrected')
                      : sheet.rendered_at
                        ? t('state.printed')
                        : t('state.draft')}
                  </span>
                  <time className="text-body-s text-ink-500" data-numeric>
                    {fmt.date(sheet.created_at)}
                  </time>
                  <IconChevronRight size={16} className="text-ink-300" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
