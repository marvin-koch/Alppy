'use client';

import {
  Button,
  Card,
  ErrorState,
  Field,
  LoadingState,
  IconPrint,
  IconSheet,
  Input,
  Select,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useMemo, useRef, useState } from 'react';

import { AddExerciseModal } from '@/components/sheet-builder/AddExerciseModal';
import { DraftPreview } from '@/components/sheet-builder/DraftPreview';
import { ExercisePicker } from '@/components/sheet-builder/ExercisePicker';
import { ProposeTab } from '@/components/sheet-builder/ProposeTab';
import { SectionPicker } from '@/components/sheet-builder/SectionPicker';
import { SheetComposer } from '@/components/sheet-builder/SheetComposer';
import {
  draftHasMixedLanguages,
  draftLanguage,
  useDraftSheet,
} from '@/components/sheet-builder/useDraftSheet';
import { useRouter } from '@/i18n/navigation';
import { apiErrorMessage } from '@/lib/api/error-message';
import {
  useChapters,
  useClasses,
  useCreateSheet,
  useSourceSections,
  useSources,
  useSubjects,
} from '@/lib/api/queries';
import type { SourceSectionOut, Uuid } from '@/lib/api/types';
import { useScope } from '@/lib/scope';

export default function SheetBuilderPage() {
  const t = useTranslations('builder');
  const ts = useTranslations('sheets');
  const tc = useTranslations('common');
  const te = useTranslations('errors');
  const locale = useLocale();
  const router = useRouter();
  const scope = useScope();

  const classes = useClasses();
  const subjects = useSubjects();
  const sources = useSources();

  const [classId, setClassId] = useState('');
  const [subjectId, setSubjectId] = useState('');
  // Default to what the shell is scoped to rather than to whichever class sorts
  // first: arriving from a class you were looking at and being silently
  // switched to another one is how a sheet gets built for the wrong pupils.
  const activeClass = classId || scope.classId || classes.data?.[0]?.id || '';
  const activeSubject = subjectId || scope.subjectId || subjects.data?.[0]?.id || '';

  const chapters = useChapters(activeSubject || undefined);

  const [title, setTitle] = useState('');
  const [sourceId, setSourceId] = useState<Uuid | ''>('');
  const [section, setSection] = useState<SourceSectionOut | null>(null);
  const [adding, setAdding] = useState(false);
  // Closed by default: the two working columns get the room, and the page count
  // the teacher actually needs while choosing lives in the composer instead.
  const [previewOpen, setPreviewOpen] = useState(false);

  const draft = useDraftSheet();
  const create = useCreateSheet();
  const composer = useRef<HTMLDivElement | null>(null);

  // A source belongs to exactly one subject, so a document chosen under
  // "Mathematics" must not stay selected when the teacher switches to German.
  const subjectSources = useMemo(
    () => (sources.data ?? []).filter((source) => source.status === 'succeeded'),
    [sources.data],
  );

  const sections = useSourceSections(sourceId || null);

  // Land on the first chapter that has been read, so the picker has something
  // in it. Falling back to the first chapter overall keeps the outline
  // reachable when none has been extracted yet.
  useEffect(() => {
    if (!sections.data?.length) {
      setSection(null);
      return;
    }
    setSection((current) => {
      if (current && sections.data.some((row) => row.id === current.id)) {
        return sections.data.find((row) => row.id === current.id) ?? current;
      }
      return (
        sections.data.find((row) => row.extracted_at !== null || row.exercise_count > 0) ??
        sections.data[0] ??
        null
      );
    });
  }, [sections.data]);

  const selectedSource = subjectSources.find((source) => source.id === sourceId) ?? null;
  const sheetLanguage = draftLanguage(draft.items, locale);
  const mixedLanguages = draftHasMixedLanguages(draft.items);

  function onCreate() {
    create.mutate(
      {
        class_id: activeClass,
        subject_id: activeSubject,
        title: title || ts('new'),
        language: sheetLanguage,
        target: 'class',
        intent: null,
        items: draft.items.map((item, index) => ({
          exercise_id: item.exercise.id,
          position: index,
          ...(item.override ? { statement_override: item.override } : {}),
        })),
      },
      { onSuccess: (sheet) => router.push(`/sheets/${sheet.id}`) },
    );
  }

  const generate = (
    <div className="flex flex-col gap-2">
      {mixedLanguages ? (
        <p className="text-body-s text-warn-600" role="status">
          {ts('mixedLanguages', { language: sheetLanguage.toUpperCase() })}
        </p>
      ) : null}
      {create.isError ? (
        <p className="text-body-s text-danger-600" role="alert">
          {apiErrorMessage(create.error, te) || ts('createFailed')}
        </p>
      ) : null}
      <Button
        variant="primary"
        block
        leadingIcon={<IconPrint />}
        onClick={onCreate}
        loading={create.isPending}
        busyLabel={ts('generating')}
        disabled={draft.count === 0}
      >
        {t('generate')}
      </Button>
      <p className="text-center text-body-s text-ink-500">{ts('bothSheets')}</p>
    </div>
  );

  // Every screen ships loading and error states (CLAUDE.md). `sources` belongs
  // in both: a failed document list would otherwise render as an empty picker,
  // which reads as "you have no textbooks" rather than "this did not load".
  if (classes.isError || subjects.isError || sources.isError) {
    return (
      <ErrorState
        title={te('generic')}
        description={apiErrorMessage(classes.error ?? subjects.error ?? sources.error, te)}
      />
    );
  }

  if (classes.isPending || subjects.isPending || sources.isPending) {
    return (
      <div className="mx-auto max-w-[1400px]">
        <h1 className="mb-6">{ts('builder')}</h1>
        <LoadingState shape="cards" label={tc('loading')} rows={2} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1400px] pb-20 lg:pb-0">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1>{ts('builder')}</h1>
          <p className="mt-1 text-body-s text-ink-500">{ts('bothSheets')}</p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          leadingIcon={<IconSheet />}
          aria-pressed={previewOpen}
          onClick={() => setPreviewOpen((open) => !open)}
        >
          {previewOpen ? t('hidePreview') : t('showPreview')}
        </Button>
      </div>

      <Card className="mb-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Field label={ts('classLabel')}>
            <Select value={activeClass} onChange={(e) => setClassId(e.currentTarget.value)}>
              {(classes.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code}
                  {c.label ? ` — ${c.label}` : ''}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={ts('subjectLabel')}>
            <Select
              value={activeSubject}
              onChange={(e) => {
                setSubjectId(e.currentTarget.value);
                // A source and a chapter both belong to a subject; keeping
                // either would filter on another subject's material.
                setSourceId('');
                setSection(null);
              }}
            >
              {(subjects.data ?? []).map((sub) => (
                <option key={sub.id} value={sub.id}>
                  {sub.labels[locale] ?? sub.labels.en ?? sub.key}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={ts('sheetTitle')}>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label={t('document')}>
            <Select
              value={sourceId}
              onChange={(e) => {
                setSourceId(e.currentTarget.value as Uuid | '');
                setSection(null);
              }}
            >
              <option value="">{t('documentPlaceholder')}</option>
              {subjectSources.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.filename} · {source.exercise_count}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        {selectedSource?.notice ? (
          <p className="mt-3 text-body-s text-warn-600" role="status">
            {selectedSource.notice}
          </p>
        ) : null}

        {sourceId ? (
          <div className="mt-4">
            <SectionPicker
              sourceId={sourceId}
              section={section}
              onSelect={(next) => setSection(next)}
            />
          </div>
        ) : null}
      </Card>

      <Tabs defaultValue="document">
        <TabsList>
          <TabsTrigger value="document">{t('tabDocument')}</TabsTrigger>
          <TabsTrigger value="propose">{t('tabPropose')}</TabsTrigger>
        </TabsList>

        <TabsContent value="document">
          <BuilderColumns
            previewOpen={previewOpen}
            picker={
              <ExercisePicker sourceId={sourceId || null} section={section} draft={draft} />
            }
            composer={
              <div ref={composer}>
                <SheetComposer draft={draft} onAdd={() => setAdding(true)} footer={generate} />
              </div>
            }
            preview={
              activeClass && activeSubject ? (
                <DraftPreview
                  classId={activeClass}
                  subjectId={activeSubject}
                  title={title || ts('new')}
                  language={sheetLanguage}
                  items={draft.items}
                />
              ) : null
            }
          />
        </TabsContent>

        <TabsContent value="propose">
          <BuilderColumns
            previewOpen={previewOpen}
            picker={
              <ProposeTab
                classId={activeClass}
                subjectId={activeSubject}
                chapters={chapters.data ?? []}
                draft={draft}
              />
            }
            composer={
              <div ref={composer}>
                <SheetComposer draft={draft} onAdd={() => setAdding(true)} footer={generate} />
              </div>
            }
            preview={
              activeClass && activeSubject ? (
                <DraftPreview
                  classId={activeClass}
                  subjectId={activeSubject}
                  title={title || ts('new')}
                  language={sheetLanguage}
                  items={draft.items}
                />
              ) : null
            }
          />
        </TabsContent>
      </Tabs>

      {/* On a phone the composer sits below a list twenty rows long, so ticking
          an exercise would otherwise produce no visible feedback at all. This
          is the acknowledgement and the way back to it — plan.md §9: mobile is
          not a degraded desktop. Above the app's own bottom tabs (`bottom-14`),
          never over them. */}
      {draft.count > 0 ? (
        <div
          className="fixed inset-x-0 bottom-14 z-20 flex items-center gap-3 border-t border-line bg-surface px-4 py-3 shadow-[0_-10px_30px_-12px_rgb(27_23_53_/_18%)] lg:hidden"
          role="status"
        >
          <div className="min-w-0 flex-grow">
            <p className="font-display font-semibold">
              {t('exerciseCount', { count: draft.count })}
            </p>
            <p className="text-body-s text-ink-500">
              {t('pagesA4', { count: draft.minPages })}
            </p>
          </div>
          <Button
            variant="primary"
            onClick={() => composer.current?.scrollIntoView({ block: 'start' })}
          >
            {t('onSheet')}
          </Button>
        </div>
      ) : null}

      {activeSubject ? (
        <AddExerciseModal
          open={adding}
          onOpenChange={setAdding}
          subjectId={activeSubject}
          language={sheetLanguage}
          onCreated={(exercise) => draft.add(exercise)}
        />
      ) : null}
    </div>
  );
}

/**
 * Two columns, or three when the preview is open.
 *
 * The preview does not overlay the work: the picker and the composer narrow to
 * make room for it, so the teacher never loses their place in a chapter to look
 * at the paper. Below `lg` everything stacks, in the order the work happens.
 */
function BuilderColumns({
  previewOpen,
  picker,
  composer,
  preview,
}: {
  previewOpen: boolean;
  picker: React.ReactNode;
  composer: React.ReactNode;
  preview: React.ReactNode;
}) {
  return (
    <div
      className={
        previewOpen
          ? 'grid grid-cols-1 items-start gap-6 lg:grid-cols-2 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)_minmax(0,1fr)]'
          : 'grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]'
      }
    >
      {picker}
      {composer}
      {previewOpen ? <div className="lg:col-span-2 xl:col-span-1">{preview}</div> : null}
    </div>
  );
}
