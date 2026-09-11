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
  type MasteryBand,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { use, useMemo } from 'react';

import { Link } from '@/i18n/navigation';
import { useBandLabels } from '@/lib/bands';
import { useClass, useClassMastery, useCurriculumTree } from '@/lib/api/queries';
import type { Uuid } from '@/lib/api/types';
import { useClassSubject } from '@/lib/use-class-subject';
import { RevealNames } from '@/components/RevealNames';
import { useDiscretion } from '@/lib/discreet';
import { studentSortName } from '@/lib/studentName';
import { isNotFound, requestIdOf } from '@/lib/api/error-message';
import { NotFoundState } from '@/components/NotFoundState';

/**
 * One Competence, for one class.
 *
 * Scoped to a class rather than living at `/competences/{id}`: a band is a
 * claim about a group of children, so a Competence page with no class behind
 * it could only show the curriculum text — which is the one thing a teacher
 * already has.
 */
export default function CompetencePage({
  params,
}: {
  params: Promise<{ classId: string; competencyId: string }>;
}) {
  const { classId, competencyId } = use(params);
  const t = useTranslations('curriculum');
  const tnav = useTranslations('nav');
  const { hideNames } = useDiscretion();
  const tt = useTranslations('tree');
  const tm = useTranslations('mastery');
  const te = useTranslations('errors.generic');
  const a11y = useTranslations('a11y');
  const locale = useLocale();
  const bandLabels = useBandLabels();

  const klass = useClass(classId as Uuid);
  const { subjectId } = useClassSubject(klass.data);

  const tree = useCurriculumTree(classId as Uuid, subjectId ? { subjectId } : {});
  // From the matrix, not a second request: `MasteryMatrixOut` already carries
  // the roster it scored, so `/classes/{id}/students` was fetching every
  // child's name again to label rows this response can label itself.
  const matrix = useClassMastery(classId as Uuid, subjectId ? { subjectId } : {});
  const students = matrix.data?.students;

  const branch = tree.data?.branches.find((b) => b.subject_id === subjectId) ?? null;
  const competence = branch?.competences.find((c) => c.competency_id === competencyId) ?? null;

  const label = (labels: Record<string, string> | undefined, fallback: string) =>
    labels?.[locale] ?? labels?.fr ?? fallback;

  // One cell per student, NOT a roll-up. A Competence is a leaf of the mastery
  // model, so the honest per-pupil figure already exists — combining anything
  // here would be inventing a second scoring rule beside `roll_up_mastery`.
  const rows = useMemo(() => {
    const byStudent = new Map(
      (matrix.data?.cells ?? [])
        .filter((c) => c.competency_id === competencyId)
        .map((c) => [c.student_id, c]),
    );
    return (students ?? []).map((s) => ({
      id: s.id,
      name: hideNames ? s.uid : studentSortName(s),
      uid: s.uid,
      cell: byStudent.get(s.id) ?? null,
    }));
  }, [students, matrix.data, competencyId, hideNames]);

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
    { label: competence?.code ?? '', key: 'competence' },
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

  if (!competence) {
    return (
      <div className="mx-auto max-w-4xl">
        {header}
        <EmptyState
          illustration={<IlloCompass />}
          title={t('competenceMissing.title')}
          description={t('competenceMissing.body')}
        />
      </div>
    );
  }

  const { assessed_count: assessed, child_count: total } = competence.mastery;

  return (
    <div className="mx-auto max-w-4xl">
      {header}

      {/* `items-start`: a ConceptTag is a pill, and a flex column stretches
          its children to full width by default — it rendered as a box the
          width of the page. */}
      <header className="mb-6 flex flex-col items-start gap-3">
        <ConceptTag code={competence.code} />
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h1>{label(competence.labels, competence.code)}</h1>
          {/* Only rendered when projector mode is on (G27). */}
          <RevealNames />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <MasteryBandTag
            band={competence.mastery.band as MasteryBand}
            label={bandLabels[competence.mastery.band as MasteryBand]}
            caption={
              total > 0 && assessed < total ? t('themesAssessed', { assessed, total }) : undefined
            }
          />
          {/* Only when it adds something: with one Theme the weakest band IS
              the band, and repeating it says nothing. */}
          {competence.mastery.weakest_band &&
          competence.mastery.weakest_band !== competence.mastery.band ? (
            <span className="text-body-s text-ink-500">
              {t('weakestIs', {
                band: bandLabels[competence.mastery.weakest_band as MasteryBand],
              })}
            </span>
          ) : null}
        </div>
      </header>

      <Card className="mb-4">
        <h2 className="mb-3 text-h3">{t('themes')}</h2>
        {competence.themes.length === 0 ? (
          <p className="text-body-s text-ink-500">{tt('empty')}</p>
        ) : (
          <ul className="flex list-none flex-col gap-1 p-0">
            {competence.themes.map((theme) => {
              const partial =
                theme.mastery.child_count > 0 &&
                theme.mastery.assessed_count < theme.mastery.child_count;
              return (
                <li key={theme.chapter_id}>
                  <Link
                    href={`/classes/${classId}/themes/${theme.chapter_id}`}
                    className="flex min-h-11 flex-wrap items-center gap-3 rounded-md px-2 py-2 no-underline hover:bg-primary-050"
                  >
                    <span className="min-w-0 flex-1 font-semibold text-ink-900">
                      {label(theme.labels, theme.key)}
                    </span>
                    <span className="text-body-s text-ink-500">
                      {tt('sheetCount', { count: theme.sheet_count })}
                    </span>
                    <MasteryBandTag
                      band={theme.mastery.band as MasteryBand}
                      label={bandLabels[theme.mastery.band as MasteryBand]}
                      caption={
                        partial
                          ? tm('coverage', {
                              assessed: theme.mastery.assessed_count,
                              total: theme.mastery.child_count,
                            })
                          : undefined
                      }
                    />
                    <IconChevronRight size={16} className="text-ink-300" aria-hidden />
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Card>
        <h2 className="mb-1 text-h3">{t('students')}</h2>
        {/* One cell each, not a roll-up: on this page the pupil's figure for
            this competency is the model's own leaf value. */}
        <p className="mb-3 text-body-s text-ink-500">{t('studentsOnThis')}</p>
        <ul className="flex list-none flex-col gap-1 p-0">
          {rows.map((row) => (
            <li key={row.id}>
              <Link
                href={`/classes/${classId}/students/${row.id}`}
                className="flex min-h-11 flex-wrap items-center gap-3 rounded-md px-2 py-1.5 no-underline hover:bg-primary-050"
              >
                <span className="min-w-0 flex-1 font-semibold text-ink-900">{row.name}</span>
                <span className="font-mono text-body-s text-ink-500">{row.uid}</span>
                <MasteryBandTag
                  band={(row.cell?.band ?? 'none') as MasteryBand}
                  label={bandLabels[(row.cell?.band ?? 'none') as MasteryBand]}
                />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
