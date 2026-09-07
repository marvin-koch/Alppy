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
  IconEdit,
  IconButton,
  IlloCompass,
  Input,
  LoadingState,
  Panel,
  ProvenancePanel,
  Select,
  Textarea,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useRouter } from '@/i18n/navigation';
import { useScope } from '@/lib/scope';
import {
  useChapters,
  useClasses,
  useCreateSheet,
  useProposeSheet,
  useSubjects,
} from '@/lib/api/queries';
import type { ExerciseProposal } from '@/lib/api/types';
import { optionLetters } from '@/lib/optionLetters';

export default function SheetBuilderPage() {
  const t = useTranslations('sheets');
  const tc = useTranslations('common');
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
  // These had no setters: the builder always used the first class and the
  // first subject, so a teacher with two classes could only build for one.
  const [classId, setClassId] = useState('');
  const [subjectId, setSubjectId] = useState('');
  // Default to what the shell is scoped to rather than to whichever class
  // sorts first: arriving here from a class you were just looking at and being
  // silently switched to another one is how a sheet gets built for the wrong
  // pupils. An explicit choice on this screen still wins.
  const scope = useScope();
  const activeClass = classId || scope.classId || classes.data?.[0]?.id || '';
  const activeSubject = subjectId || scope.subjectId || subjects.data?.[0]?.id || '';
  const chapters = useChapters(activeSubject || undefined);

  const [title, setTitle] = useState('');
  const [intent, setIntent] = useState('');
  const [chapterIds, setChapterIds] = useState<string[]>([]);
  const [kept, setKept] = useState<ExerciseProposal[]>([]);
  /** Teacher's printed wording, keyed by exercise id. Never written back to
   *  the exercise: it rides along as the sheet item's `statement_override`, so
   *  the source keeps its own text and its provenance. */
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<string | null>(null);

  const propose = useProposeSheet();
  const create = useCreateSheet();

  // The sheet's language is the one the exercises are written in, not the one
  // the teacher's interface happens to be in. Taking kept[0] meant reordering
  // flipped a French sheet to German.
  const sheetLanguage = ((): 'fr' | 'de' | 'en' => {
    const counts = new Map<string, number>();
    for (const p of kept) {
      const l = p.exercise.language;
      if (l) counts.set(l, (counts.get(l) ?? 0) + 1);
    }
    let best: string | null = null;
    for (const [l, n] of counts) if (best === null || n > (counts.get(best) ?? 0)) best = l;
    return (best ?? locale) as 'fr' | 'de' | 'en';
  })();
  const mixedLanguages = new Set(kept.map((p) => p.exercise.language).filter(Boolean)).size > 1;

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
        language: sheetLanguage,
        target: 'class',
        intent: intent || null,
        items: kept.map((p, i) => ({
          exercise_id: p.exercise.id,
          position: i,
          ...(overrides[p.exercise.id] ? { statement_override: overrides[p.exercise.id] } : {}),
        })),
      },
      { onSuccess: (sheet) => router.push(`/sheets/${sheet.id}`) },
    );
  }

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-6">{t('builder')}</h1>

      <Card className="mb-6">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label={t('classLabel')}>
            <Select value={activeClass} onChange={(e) => setClassId(e.currentTarget.value)}>
              {(classes.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code}
                  {c.label ? ` — ${c.label}` : ''}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('subjectLabel')}>
            <Select
              value={activeSubject}
              onChange={(e) => {
                setSubjectId(e.currentTarget.value);
                // Chapters belong to a subject; keeping the old selection
                // would silently filter on chapters of another subject.
                setChapterIds([]);
              }}
            >
              {(subjects.data ?? []).map((sub) => (
                <option key={sub.id} value={sub.id}>
                  {sub.labels[locale] ?? sub.labels.en ?? sub.key}
                </option>
              ))}
            </Select>
          </Field>
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

        {/* A failed proposal used to fall through to the empty state, which
            tells the teacher they have no sheets — the wrong thing entirely. */}
        {propose.isError ? (
          <p className="mt-3 text-body-s text-danger-600" role="alert">
            {t('proposeFailed')}
          </p>
        ) : null}
        {create.isError ? (
          <p className="mt-3 text-body-s text-danger-600" role="alert">
            {t('createFailed')}
          </p>
        ) : null}
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
          {/* Exercise content follows the language of the source material, so a
              chapter with fewer French items than requested falls back to
              German ones. Printing that silently is the defect; saying so is
              not. */}
          {mixedLanguages ? (
            <p className="mb-3 text-body-s text-warn-600" role="status">
              {t('mixedLanguages', { language: sheetLanguage.toUpperCase() })}
            </p>
          ) : null}

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

                      {editing === p.exercise.id ? (
                        <div>
                          <Textarea
                            aria-label={t('editStatement')}
                            value={overrides[p.exercise.id] ?? p.exercise.statement}
                            onChange={(e) => {
                              // Read the value before the updater runs:
                              // `currentTarget` is null by the time React
                              // calls a lazy updater, which threw and took the
                              // whole editor down with it.
                              const next = e.currentTarget.value;
                              setOverrides((o) => ({ ...o, [p.exercise.id]: next }));
                            }}
                            rows={3}
                          />
                          <div className="mt-2 flex gap-2">
                            <Button size="sm" onClick={() => setEditing(null)}>
                              {tc('done')}
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => {
                                setOverrides(({ [p.exercise.id]: _drop, ...rest }) => rest);
                                setEditing(null);
                              }}
                            >
                              {t('resetStatement')}
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <p data-student-facing>
                          {overrides[p.exercise.id] ?? p.exercise.statement}
                          {overrides[p.exercise.id] ? (
                            <Badge variant="neutral" className="ml-2">
                              {t('edited')}
                            </Badge>
                          ) : null}
                        </p>
                      )}

                      {p.exercise.options ? (
                        <ol className="mt-2 flex list-none flex-wrap gap-3 p-0 text-body-s">
                          {p.exercise.options.map((o, i) => (
                            <li key={i} className="text-ink-700">
                              {/* The glyphs the sheet actually prints: MCQ is
                                  ABCD, true/false is V/F, R/F or T/F by the
                                  exercise's own language. Hardcoding ABCD made
                                  the preview disagree with the paper. */}
                              <span className="mono mr-1">
                                {optionLetters(p.exercise.type, p.exercise.language)[i] ?? ''}
                              </span>
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
                        label={t('editStatement')}
                        icon={<IconEdit />}
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setEditing((cur) => (cur === p.exercise.id ? null : p.exercise.id))
                        }
                      />
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
