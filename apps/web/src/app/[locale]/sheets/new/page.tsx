'use client';

import {
  Button,
  ErrorState,
  Field,
  IconChevronLeft,
  IconPrint,
  IconSheet,
  LoadingState,
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
import { ThemePicker, canFile, type ThemeSelection } from '@/components/sheet-builder/ThemePicker';
import {
  draftHasMixedLanguages,
  draftLanguage,
  toSheetItemIn,
  useDraftSheet,
} from '@/components/sheet-builder/useDraftSheet';
import { Link, useRouter } from '@/i18n/navigation';
import { apiErrorMessage, requestIdOf } from '@/lib/api/error-message';
import {
  useChapters,
  useCreateSheet,
  useCurriculumTree,
  useSourceSections,
  useSources,
} from '@/lib/api/queries';
import type { SourceSectionOut, Uuid } from '@/lib/api/types';
import { useScope } from '@/lib/scope';

/**
 * The builder.
 *
 * One page, two columns, three ways in. The left column is where exercises
 * come from — a textbook chapter, a retrieval across every book, or the
 * teacher's own keyboard — and the right column is the paper, in the order it
 * prints. The class and the subject are the shell's, chosen in the sidebar:
 * they were repeated here as two more selects, and a sheet built under one
 * scope while the sidebar showed another was a sheet for the wrong pupils.
 */
export default function SheetBuilderPage() {
  const t = useTranslations('builder');
  const ts = useTranslations('sheets');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const tcode = useTranslations('errors.code');
  const locale = useLocale();
  const router = useRouter();
  const scope = useScope();

  const sources = useSources();
  const activeClass = scope.classId ?? '';
  const activeSubject = scope.subjectId ?? '';
  const chapters = useChapters(activeSubject || undefined);

  const [title, setTitle] = useState('');
  // The Theme this sheet is about — the builder's root. `'unfiled'` narrows
  // the exercise list to what the book left untagged; it is NOT a place a
  // sheet can be filed, so `canFile` gates the generate button below.
  const [theme, setTheme] = useState<ThemeSelection>(null);
  const [sourceId, setSourceId] = useState<Uuid | ''>('');
  const [section, setSection] = useState<SourceSectionOut | null>(null);
  const [adding, setAdding] = useState(false);
  // Closed by default: the two working columns get the room, and the page
  // count the teacher needs while choosing lives in the composer instead.
  const [previewOpen, setPreviewOpen] = useState(false);

  // Only for the "Sans thème" count in the picker: how many exercises in this
  // Branch the ingest could not tag with a chapter at all.
  const tree = useCurriculumTree(
    activeClass || null,
    activeSubject ? { subjectId: activeSubject } : {},
  );
  const unfiledExerciseCount =
    tree.data?.branches.find((b) => b.subject_id === activeSubject)?.unfiled_exercise_count ?? 0;

  // Keyed on the pair the draft belongs to: coming back to a different class
  // must not hand the teacher the other one's exercises (F19).
  const draft = useDraftSheet(
    activeClass && activeSubject ? `${activeClass}:${activeSubject}` : null,
  );
  const create = useCreateSheet();
  const composer = useRef<HTMLDivElement | null>(null);

  // A source and a chapter both belong to a subject; keeping either across a
  // subject change would filter on another subject's material.
  useEffect(() => {
    setSourceId('');
    setSection(null);
    setTheme(null);
  }, [activeSubject]);

  const readySources = useMemo(
    () => (sources.data ?? []).filter((source) => source.status === 'succeeded'),
    [sources.data],
  );

  const sections = useSourceSections(sourceId || null);

  // Land on the first chapter that has been read, so the picker has something
  // in it; the first chapter overall keeps the outline reachable otherwise.
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

  const selectedSource = readySources.find((source) => source.id === sourceId) ?? null;
  const sheetLanguage = draftLanguage(draft.items, locale);
  const mixedLanguages = draftHasMixedLanguages(draft.items);

  // The chapter names the sheet unless the teacher does. A list of twelve
  // sheets all called "New sheet" is what the old default produced.
  // Only a chapter that holds exercises lends its name: an unread book names
  // its chapters by page range, and "p. 1–4" is no title for a sheet.
  const suggestedTitle = section && section.exercise_count > 0 ? section.title : '';
  const effectiveTitle = title.trim() || suggestedTitle || ts('new');

  function onCreate() {
    create.mutate(
      {
        class_id: activeClass,
        subject_id: activeSubject,
        chapter_id: canFile(theme) ? theme.chapter_id : null,
        title: effectiveTitle,
        language: sheetLanguage,
        target: 'class',
        intent: null,
        items: draft.items.map((item, index) => toSheetItemIn(item, index)),
        default_points_correct: draft.bareme.correct,
        default_points_penalty: draft.bareme.penalty,
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
          {apiErrorMessage(create.error, tcode) || ts('createFailed')}
        </p>
      ) : null}
      {!canFile(theme) && draft.count > 0 ? (
        <p className="text-body-s text-warn-600" role="status">
          {t('themeRequired')}
        </p>
      ) : null}
      <Button
        variant="primary"
        block
        leadingIcon={<IconPrint />}
        onClick={onCreate}
        loading={create.isPending}
        busyLabel={ts('generating')}
        // A new sheet must be filed under a real Theme. `unfiled` exists to
        // FIND untagged exercises, not to store a sheet nobody classified.
        disabled={draft.count === 0 || !canFile(theme)}
      >
        {t('generate')}
      </Button>
      <p className="text-center text-body-s text-ink-500">{t('generateHelp')}</p>
    </div>
  );

  if (sources.isError) {
    return (
      <ErrorState
        title={te('title')}
        description={apiErrorMessage(sources.error, tcode)}
        requestId={requestIdOf(sources.error)}
      />
    );
  }

  if (scope.isLoading || sources.isPending) {
    return (
      <div className="mx-auto max-w-[1400px]">
        <h1 className="mb-6">{ts('new')}</h1>
        <LoadingState shape="cards" label={tc('loading')} rows={2} />
      </div>
    );
  }

  const scopeLine = [
    scope.currentClass?.code,
    scope.currentSubject
      ? (scope.currentSubject.labels[locale] ??
        scope.currentSubject.labels.fr ??
        scope.currentSubject.key)
      : null,
  ]
    .filter(Boolean)
    .join(' · ');

  const preview =
    activeClass && activeSubject ? (
      <DraftPreview
        classId={activeClass}
        subjectId={activeSubject}
        title={effectiveTitle}
        language={sheetLanguage}
        items={draft.items}
        bareme={draft.bareme}
      />
    ) : null;

  const composerColumn = (
    <div ref={composer}>
      <SheetComposer
        draft={draft}
        onAdd={() => setAdding(true)}
        footer={generate}
        previewOpen={previewOpen}
        onTogglePreview={() => setPreviewOpen((open) => !open)}
      />
    </div>
  );

  return (
    <div className="mx-auto max-w-[1400px] pb-20 lg:pb-0">
      <Link
        href="/sheets"
        className="mb-3 inline-flex min-h-11 items-center gap-1 text-body-s font-bold text-ink-500 no-underline hover:text-primary-700"
      >
        <IconChevronLeft size={18} aria-hidden />
        {ts('title')}
      </Link>

      {/* The title is the heading. A sheet is named the way a note is: type
          over the placeholder, and the chapter's own name stands in until
          then. There is no separate "title" field to find. */}
      <header className="mb-6">
        <h1 className="m-0">
          <label className="block">
            <span className="sr-only">{ts('sheetTitle')}</span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={suggestedTitle || t('titlePlaceholder')}
              maxLength={200}
              className="w-full rounded-sm border-0 bg-transparent px-0 font-display text-h1 font-bold text-ink-900 placeholder:text-ink-300 focus:outline-none focus-visible:shadow-[0_0_0_4px_var(--c-primary-100)]"
            />
          </label>
        </h1>
        {scopeLine ? (
          <p className="mt-1 text-body-s text-ink-500">{t('forScope', { scope: scopeLine })}</p>
        ) : null}
      </header>

      {/* The root of the builder: which Theme is this sheet about. Above the
          tabs, because it governs both of them — the document tab's exercise
          list and the propose tab's default chapters. */}
      <div className="mb-4">
        <ThemePicker
          classId={activeClass || null}
          subjectId={activeSubject || undefined}
          selection={theme}
          onSelect={setTheme}
          unfiledExerciseCount={unfiledExerciseCount}
        />
      </div>

      <Tabs defaultValue="document">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <TabsList className="mb-0">
            <TabsTrigger value="document">{t('tabDocument')}</TabsTrigger>
            <TabsTrigger value="propose">{t('tabPropose')}</TabsTrigger>
          </TabsList>
          {/* The document lives beside the tab it belongs to, and nowhere
              else: it used to sit in a bar above both tabs, where it filtered
              a list the retrieval tab never showed. */}
          {readySources.length > 0 ? (
            <Field label={t('document')} hideLabel className="w-full sm:w-auto sm:min-w-72">
              <Select
                value={sourceId}
                onChange={(event) => {
                  setSourceId(event.currentTarget.value as Uuid | '');
                  setSection(null);
                }}
              >
                <option value="">{t('documentPlaceholder')}</option>
                {readySources.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.filename}
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
        </div>

        <TabsContent value="document">
          <BuilderColumns
            previewOpen={previewOpen}
            picker={
              <div className="flex flex-col gap-3">
                {selectedSource?.notice ? (
                  <p className="text-body-s text-warn-600" role="status">
                    {selectedSource.notice}
                  </p>
                ) : null}
                {sourceId ? (
                  <SectionPicker
                    sourceId={sourceId}
                    section={section}
                    onSelect={(next) => setSection(next)}
                  />
                ) : null}
                <ExercisePicker
                  sourceId={sourceId || null}
                  section={section}
                  themeFilter={
                    theme === 'unfiled' ? 'none' : canFile(theme) ? theme.chapter_id : undefined
                  }
                  draft={draft}
                  sources={readySources}
                  onChooseSource={(id) => {
                    setSourceId(id);
                    setSection(null);
                  }}
                />
              </div>
            }
            composer={composerColumn}
            preview={preview}
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
            composer={composerColumn}
            preview={preview}
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
          className="fixed inset-x-0 bottom-14 z-20 flex items-center gap-3 border-t border-line bg-surface px-4 py-3 shadow-ambient-up lg:hidden"
          role="status"
        >
          <div className="min-w-0 flex-grow">
            <p className="font-display font-semibold">
              {t('exerciseCount', { count: draft.count })}
            </p>
            <p className="text-body-s text-ink-500">{t('pagesA4', { count: draft.minPages })}</p>
          </div>
          <Button
            variant="primary"
            leadingIcon={<IconSheet />}
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
