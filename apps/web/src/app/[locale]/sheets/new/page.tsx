'use client';

import {
  AiBadge,
  Badge,
  Button,
  Card,
  Chip,
  EmptyState,
  Field,
  IconChevronDown,
  IconChevronUp,
  IconClose,
  IconButton,
  IlloCompass,
  Input,
  LoadingState,
  Panel,
  ProvenancePanel,
  Textarea,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useRouter } from '@/i18n/navigation';
import {
  useChapters,
  useClasses,
  useCreateSheet,
  useProposeSheet,
  useSubjects,
} from '@/lib/api/queries';
import type { ExerciseProposal } from '@/lib/api/types';

export default function SheetBuilderPage() {
  const t = useTranslations('sheets');
  const tx = useTranslations('exercise');
  const ta = useTranslations('adaptive');
  const locale = useLocale();
  const provenanceLabels = {
    source: t('source'),
    page: t('page'),
    excerpt: t('provenance'),
    similarity: t('similarity'),
  };
  const router = useRouter();

  const classes = useClasses();
  const subjects = useSubjects();
  const [classId] = useState('');
  const [subjectId] = useState('');
  const chapters = useChapters(subjectId || undefined);

  const [title, setTitle] = useState('');
  const [intent, setIntent] = useState('');
  const [chapterIds, setChapterIds] = useState<string[]>([]);
  const [kept, setKept] = useState<ExerciseProposal[]>([]);

  const propose = useProposeSheet();
  const create = useCreateSheet();

  const activeClass = classId || classes.data?.[0]?.id || '';
  const activeSubject = subjectId || subjects.data?.[0]?.id || '';

  function onPropose() {
    propose.mutate(
      {
        class_id: activeClass,
        subject_id: activeSubject,
        chapter_ids: chapterIds,
        intent: intent || null,
        count: 12,
      },
      { onSuccess: (r) => setKept(r.proposals) },
    );
  }

  function move(index: number, delta: number) {
    setKept((current) => {
      const next = [...current];
      const target = index + delta;
      if (target < 0 || target >= next.length) return current;
      const [item] = next.splice(index, 1);
      if (item) next.splice(target, 0, item);
      return next;
    });
  }

  function onCreate() {
    create.mutate(
      {
        class_id: activeClass,
        subject_id: activeSubject,
        title: title || t('new'),
        language: (kept[0]?.exercise.language ?? locale) as 'fr' | 'de' | 'en',
        target: 'class',
        intent: intent || null,
        items: kept.map((p, i) => ({ exercise_id: p.exercise.id, position: i })),
      },
      { onSuccess: (sheet) => router.push(`/sheets/${sheet.id}`) },
    );
  }

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-6">{t('builder')}</h1>

      <Card className="mb-6">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label={t('sheetTitle')}>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label={t('intent')} help={t('intentHelp')}>
            <Textarea
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              placeholder={t('intentPlaceholder')}
              rows={2}
            />
          </Field>
        </div>

        {chapters.data && chapters.data.length > 0 ? (
          <fieldset className="mt-4 border-0 p-0">
            <legend className="mb-2 text-label text-ink-500">{t('chapters')}</legend>
            <ul className="flex list-none flex-wrap gap-2 p-0">
              {chapters.data.map((ch) => {
                const on = chapterIds.includes(ch.id);
                return (
                  <li key={ch.id}>
                    <button
                      type="button"
                      aria-pressed={on}
                      onClick={() =>
                        setChapterIds((c) =>
                          on ? c.filter((x) => x !== ch.id) : [...c, ch.id],
                        )
                      }
                      className="min-h-11 cursor-pointer border-0 bg-transparent p-0"
                    >
                      <Chip variant={on ? 'primary' : 'neutral'}>
                        {ch.labels?.[locale] ?? ch.key}
                      </Chip>
                    </button>
                  </li>
                );
              })}
            </ul>
          </fieldset>
        ) : null}

        <div className="mt-4">
          <Button
            variant="primary"
            onClick={onPropose}
            loading={propose.isPending}
            busyLabel={t('proposing')}
          >
            {t('propose')}
          </Button>
        </div>
      </Card>

      {propose.isPending ? (
        <LoadingState shape="list" label={t('proposing')} rows={6} />
      ) : kept.length === 0 ? (
        <EmptyState
          illustration={<IlloCompass />}
          title={t('empty.title')}
          description={t('empty.body')}
        />
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-h3">{t('selected', { count: kept.length })}</h2>
            <Button
              variant="primary"
              onClick={onCreate}
              loading={create.isPending}
              busyLabel={t('generating')}
              disabled={kept.length === 0}
            >
              {t('preview')}
            </Button>
          </div>

          <ol className="flex list-none flex-col gap-3 p-0">
            {kept.map((p, index) => (
              <li key={p.exercise.id}>
                <Panel>
                  <div className="flex items-start gap-3">
                    <span
                      className="mono mt-1 w-6 shrink-0 text-body-s text-ink-500"
                      data-numeric
                    >
                      {index + 1}
                    </span>

                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <Badge>{tx(`type.${p.exercise.type}`)}</Badge>
                        <Badge variant="neutral">
                          {tx('difficultyLevel', { level: p.exercise.difficulty })}
                        </Badge>
                        {/* The one place the mandarin is allowed. */}
                        {p.exercise.origin === 'ai_generated' ? (
                          <AiBadge label={ta('aiBadge')} />
                        ) : null}
                      </div>

                      <p data-student-facing>{p.exercise.statement}</p>

                      {p.exercise.options ? (
                        <ol className="mt-2 flex list-none flex-wrap gap-3 p-0 text-body-s">
                          {p.exercise.options.map((o, i) => (
                            <li key={i} className="text-ink-700">
                              <span className="mono mr-1">{'ABCD'[i]}</span>
                              {o}
                            </li>
                          ))}
                        </ol>
                      ) : p.exercise.type === 'open' ? (
                        <p className="mt-2 text-body-s text-ink-500">{tx('openNotGraded')}</p>
                      ) : null}

                      {/* The teacher audits this against the book on the desk. */}
                      <div className="mt-3">
                        <ProvenancePanel
                          sourceTitle={p.provenance.source_filename ?? p.provenance.reason}
                          page={p.provenance.page ?? undefined}
                          excerpt={p.provenance.excerpt ?? p.provenance.reason}
                          similarity={p.provenance.similarity ?? undefined}
                          labels={provenanceLabels}
                          aiBadge={
                            p.exercise.origin === 'ai_generated' ? (
                              <AiBadge label={ta('aiBadge')} size="sm" />
                            ) : undefined
                          }
                        />
                      </div>
                    </div>

                    <div className="flex shrink-0 flex-col gap-1">
                      <IconButton
                        label={t('moveUp')}
                        icon={<IconChevronUp />}
                        variant="ghost"
                        size="sm"
                        onClick={() => move(index, -1)}
                      />
                      <IconButton
                        label={t('moveDown')}
                        icon={<IconChevronDown />}
                        variant="ghost"
                        size="sm"
                        onClick={() => move(index, 1)}
                      />
                      <IconButton
                        label={t('remove')}
                        icon={<IconClose />}
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setKept((c) => c.filter((x) => x.exercise.id !== p.exercise.id))
                        }
                      />
                    </div>
                  </div>
                </Panel>
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}
