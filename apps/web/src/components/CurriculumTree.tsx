'use client';

import { Card, IconChevronRight, MasteryBandTag, Panel } from '@alppy/ui';

import { Link } from '@/i18n/navigation';
import { useLocale, useTranslations } from 'next-intl';

import { useBandLabels } from '@/lib/bands';
import { competenceCodes } from '@/lib/competenceCode';
import type { TreeBranchOut, Uuid } from '@/lib/api/types';

interface Props {
  /** Where the detail pages live, e.g. `/classes/{id}`. Omitted, the tree only
   *  filters — which is all the class dashboard needed before these existed. */
  basePath?: string;
  branch: TreeBranchOut | null;
  competencyId: Uuid | null;
  chapterId: Uuid | null;
  onSelectCompetence: (id: Uuid | null) => void;
  onSelectTheme: (id: Uuid | null) => void;
  isLoading?: boolean;
}

/**
 * Branch -> Competence -> Theme, as a navigable list.
 *
 * Every node carries a band, and every band carries its written label as well
 * as its tint and glyph (DC-colour-08) — an aggregate is exactly where a bare
 * colour is most tempting and least honest, because the reader cannot tell
 * whether "green" means three competencies mastered or one mastered and two
 * never examined. `coverage` says which.
 *
 * The `unfiled` bucket is rendered LAST and plainly: it is not a Theme, it
 * carries no band, and it exists so the sheets nobody has filed stay findable.
 * The API leaves it out of `competences` entirely; this component only ever
 * sees its count.
 */
export function CurriculumTree({
  basePath,
  branch,
  competencyId,
  chapterId,
  onSelectCompetence,
  onSelectTheme,
  isLoading,
}: Props) {
  const tt = useTranslations('tree');
  const tm = useTranslations('mastery');
  const tc = useTranslations('common');
  const bandLabels = useBandLabels();
  const locale = useLocale();

  const label = (labels: Record<string, string> | undefined, fallback: string) =>
    labels?.[locale] ?? labels?.fr ?? fallback;

  if (isLoading || !branch) {
    return (
      <Card className="flex flex-col gap-4">
        <h2 className="text-h3 font-display">{tt('title')}</h2>
        <p className="text-body-s text-ink-500">{isLoading ? '' : tt('empty')}</p>
      </Card>
    );
  }

  // Two editions of one curriculum code are two Competences with the same code
  // and the same sentence; the edition is appended only where that collides.
  const codeOf = competenceCodes(branch.competences);

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-h3 font-display">{tt('title')}</h2>
        {competencyId || chapterId ? (
          <button
            type="button"
            onClick={() => {
              onSelectCompetence(null);
              onSelectTheme(null);
            }}
            className="min-h-11 rounded-md px-2 text-body-s font-semibold text-primary-600 hover:bg-primary-050"
          >
            {tc('showAll')}
          </button>
        ) : (
          <MasteryBandTag
            band={branch.mastery.band}
            label={tm('branchBand', { band: bandLabels[branch.mastery.band] })}
          />
        )}
      </div>

      {branch.competences.length === 0 ? (
        <p className="text-body-s text-ink-500">{tt('empty')}</p>
      ) : null}

      {branch.competences.map((competence) => (
        <section key={competence.competency_id} className="flex flex-col gap-2">
          {/* A subdivision of the tree card, not a card of its own
              (DC-shape-01): nesting cards here would flatten the hierarchy the
              whole component exists to show. */}
          {/* The heading NARROWS. This tree used to sit beside two chained
              selects that did the same job from a second control, which is the
              duplication D45 argued against for the builder. The hierarchy is
              already drawn here, with the bands that tell you where to look —
              so clicking it is the filter. */}
          <header className="border-b border-line pb-2">
            <button
              type="button"
              aria-pressed={competence.competency_id === competencyId}
              onClick={() =>
                onSelectCompetence(
                  competence.competency_id === competencyId
                    ? null
                    : competence.competency_id,
                )
              }
              className="flex min-h-11 w-full flex-col gap-1 rounded-md px-2 py-1 text-left transition-colors hover:bg-primary-050 aria-pressed:bg-primary-100"
            >
              <span className="flex items-center gap-2">
                <span className="font-mono text-label text-ink-700">
                  {codeOf.get(competence.competency_id) ?? competence.code}
                </span>
                <span className="flex-1" />
                <MasteryBandTag
                  band={competence.mastery.band}
                  label={bandLabels[competence.mastery.band]}
                />
              </span>
              {/* The official curriculum wording, on its own line. It is a whole
                  sentence in the PER, and sharing a row with the band left both
                  truncated to nothing. */}
              <span
                className="text-body-s font-bold leading-snug"
                title={label(competence.labels, competence.code)}
              >
                {label(competence.labels, competence.code)}
              </span>
            </button>
          </header>

          <ul className="flex flex-col gap-1">
            {competence.themes.map((theme) => {
              const active = theme.chapter_id === chapterId;
              const { assessed_count: assessed, child_count: total } = theme.mastery;
              // Coverage is shown when it is INCOMPLETE and not otherwise.
              // "3 sur 3" tells a reader nothing they cannot see from the band;
              // "1 sur 3" is the whole warning (DC-content-07). Printing both
              // put a full-width caption on every row and buried the names.
              const partial = total > 0 && assessed < total;
              return (
                // The filter and the detail page are two different intents, so
                // they are two sibling controls. A link nested inside the
                // button would be interactive content inside a button — not
                // valid HTML, and a keyboard user could never reach it.
                <li key={theme.chapter_id} className="flex items-center gap-1">
                  <button
                    type="button"
                    aria-current={active ? 'true' : undefined}
                    onClick={() => onSelectTheme(active ? null : theme.chapter_id)}
                    className="flex min-h-11 w-full flex-col items-start justify-center gap-0.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-primary-050 aria-[current=true]:bg-primary-100"
                  >
                    <span className="flex w-full items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-body-s font-semibold text-ink-700">
                        {label(theme.labels, theme.key)}
                      </span>
                      {theme.sheet_count > 0 ? (
                        <span className="shrink-0 text-label text-ink-500">
                          {tt('sheetCount', { count: theme.sheet_count })}
                        </span>
                      ) : null}
                      <MasteryBandTag
                        band={theme.mastery.band}
                        label={bandLabels[theme.mastery.band]}
                      />
                    </span>
                    {partial ? (
                      <span className="text-label text-ink-500">
                        {tm('coverage', { assessed, total })}
                      </span>
                    ) : null}
                  </button>
                  {basePath ? (
                    <Link
                      href={`${basePath}/themes/${theme.chapter_id}`}
                      aria-label={tc('openNamed', {
                        name: label(theme.labels, theme.key),
                      })}
                      className="flex min-h-11 w-11 shrink-0 items-center justify-center rounded-md text-ink-500 no-underline transition-colors hover:bg-primary-050 hover:text-primary-700"
                    >
                      <IconChevronRight size={16} aria-hidden />
                    </Link>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      {/* Last, plain, and never hidden. */}
      <Panel sunken className="flex items-center gap-3">
        <span className="min-w-0 flex-1 text-body-s font-bold text-ink-700">
          {tt('unfiled')}
        </span>
        <span className="shrink-0 text-label text-ink-500">
          {tt('unfiledSheets', { count: branch.unfiled_sheet_count })}
        </span>
      </Panel>
    </Card>
  );
}
