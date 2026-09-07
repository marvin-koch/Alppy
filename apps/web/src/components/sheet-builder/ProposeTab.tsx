'use client';

import {
  AiBadge,
  Button,
  Card,
  Chip,
  EmptyState,
  IlloCompass,
  LoadingState,
  ProvenancePanel,
  Textarea,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useProposeSheet } from '@/lib/api/queries';
import { apiErrorMessage } from '@/lib/api/error-message';
import type { ChapterOut, ExerciseProposal, Uuid } from '@/lib/api/types';
import { ExerciseRow } from './ExerciseRow';
import type { DraftSheet } from './useDraftSheet';

interface Props {
  classId: Uuid;
  subjectId: Uuid;
  chapters: ChapterOut[];
  draft: DraftSheet;
}

/**
 * The retrieval path, kept beside the document path rather than replaced.
 *
 * It answers a different question. "From a document" is *I am teaching chapter
 * four of this book*; this is *find me twelve things on fractions, from
 * anywhere I own*. It also ranks across every source at once, which is the only
 * way a teacher reaches a second textbook without changing the document picker.
 *
 * Proposals feed the same draft as the picker, so a sheet can mix both.
 */
export function ProposeTab({ classId, subjectId, chapters, draft }: Props) {
  const t = useTranslations('builder');
  const ts = useTranslations('sheets');
  const ta = useTranslations('adaptive');
  const te = useTranslations('errors');
  const locale = useLocale();

  const [intent, setIntent] = useState('');
  const [chapterIds, setChapterIds] = useState<Uuid[]>([]);
  const [proposals, setProposals] = useState<ExerciseProposal[]>([]);

  const propose = useProposeSheet();

  const provenanceLabels = {
    source: ts('source'),
    page: ts('page'),
    excerpt: ts('provenance'),
    similarity: ts('similarity'),
  };

  function onPropose() {
    propose.mutate(
      {
        class_id: classId,
        subject_id: subjectId,
        chapter_ids: chapterIds,
        intent: intent || null,
        count: 12,
      },
      {
        onSuccess: (result) => {
          setProposals(result.proposals);
          // Ranked proposals arrive already on the sheet, as they always have:
          // the teacher asked for twelve and prunes what does not fit. The
          // checkboxes are how they prune, and they are the same control the
          // document tab uses, so "ticked" means the same thing on both.
          for (const proposal of result.proposals) draft.add(proposal.exercise);
        },
      },
    );
  }

  return (
    <Card className="flex flex-col gap-4">
      <h2 className="text-h3">{t('tabPropose')}</h2>

      <label className="flex flex-col gap-1.5">
        <span className="text-label text-ink-500">{ts('intent')}</span>
        <Textarea
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder={ts('intentPlaceholder')}
          rows={2}
        />
        <span className="text-body-s text-ink-500">{ts('intentHelp')}</span>
      </label>

      {chapters.length > 0 ? (
        <fieldset className="border-0 p-0">
          <legend className="mb-2 text-label text-ink-500">{ts('chapters')}</legend>
          <ul className="flex list-none flex-wrap gap-2 p-0">
            {chapters.map((chapter) => {
              const on = chapterIds.includes(chapter.id);
              return (
                <li key={chapter.id}>
                  <button
                    type="button"
                    aria-pressed={on}
                    onClick={() =>
                      setChapterIds((current) =>
                        on ? current.filter((id) => id !== chapter.id) : [...current, chapter.id],
                      )
                    }
                    className="min-h-11 cursor-pointer border-0 bg-transparent p-0"
                  >
                    <Chip variant={on ? 'primary' : 'neutral'}>
                      {chapter.labels?.[locale] ?? chapter.key}
                    </Chip>
                  </button>
                </li>
              );
            })}
          </ul>
        </fieldset>
      ) : null}

      <Button
        variant="primary"
        onClick={onPropose}
        loading={propose.isPending}
        busyLabel={ts('proposing')}
        className="self-start"
      >
        {ts('propose')}
      </Button>

      {propose.isError ? (
        <p className="text-body-s text-danger-600" role="alert">
          {apiErrorMessage(propose.error, te) || ts('proposeFailed')}
        </p>
      ) : null}

      {propose.isPending ? (
        <LoadingState shape="list" label={ts('proposing')} rows={5} />
      ) : proposals.length === 0 ? (
        <EmptyState
          illustration={<IlloCompass />}
          title={ts('empty.title')}
          description={ts('empty.body')}
          size="sm"
        />
      ) : (
        <ul className="flex list-none flex-col gap-2 p-0">
          {proposals.map((proposal) => {
            const { exercise } = proposal;
            const checked = draft.has(exercise.id);
            return (
              <li key={exercise.id}>
                <ExerciseRow
                  exercise={exercise}
                  checked={checked}
                  disabled={!checked && draft.isFull}
                  onToggle={() => draft.toggle(exercise)}
                  badges={
                    // The one place the mandarin is allowed.
                    exercise.origin === 'ai_generated' ? <AiBadge label={ta('aiBadge')} /> : null
                  }
                  footer={
                    // The teacher audits this against the book on the desk.
                    <div className="mt-3">
                      <ProvenancePanel
                        sourceTitle={
                          proposal.provenance.source_filename ?? proposal.provenance.reason
                        }
                        page={proposal.provenance.page ?? undefined}
                        excerpt={proposal.provenance.excerpt ?? proposal.provenance.reason}
                        similarity={proposal.provenance.similarity ?? undefined}
                        labels={provenanceLabels}
                        aiBadge={
                          exercise.origin === 'ai_generated' ? (
                            <AiBadge label={ta('aiBadge')} size="sm" />
                          ) : undefined
                        }
                      />
                    </div>
                  }
                />
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
