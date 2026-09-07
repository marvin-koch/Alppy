'use client';

import {
  AiBadge,
  Badge,
  Button,
  Card,
  ConceptTag,
  EmptyState,
  ErrorState,
  Field,
  IconDownload,
  IconWarning,
  IlloSummit,
  LoadingState,
  Panel,
  SegmentedControl,
  Select,
  Slider,
  Toggle,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useScope } from '@/lib/scope';
import { apiErrorMessage } from '@/lib/api/error-message';

import { AdaptiveItem } from '@/components/AdaptiveItem';
import { FeedbackNoteCard } from '@/components/FeedbackNoteCard';
import {
  useApproveAdaptive,
  useApproveFeedback,
  useBatchAdaptive,
  useDiscardFeedback,
  useFeedback,
  useGenerateFeedback,
  useClasses,
  useDiscardAdaptive,
  useSheets,
  useStudents,
  useJob,
  useProposeAdaptive,
  useRegenerateAdaptive,
  useRenderAdaptiveBatch,
  useSheet,
  useSubjects,
  useUpdateExercise,
} from '@/lib/api/queries';
import type {
  AdaptiveGenerationFailure,
  AdaptiveGroupPlan,
  AdaptiveProposeResponse,
  AdaptiveStudentPlan,
  ExerciseProposal,
  Uuid,
} from '@/lib/api/types';

type Mode = 'per_student' | 'group';

/** The class roster size is the ceiling: more groups than students is one each. */
const MIN_GROUPS = 1;

/** Every generated exercise in a plan, in the order the teacher sees them. */
function generatedIds(plan: AdaptiveProposeResponse | null): Uuid[] {
  if (!plan) return [];
  // A group's items are shared, so counting the per-student plans would count
  // the same generated row once per child in the group.
  const source: { generated: ExerciseProposal[] }[] = plan.groups.length
    ? plan.groups
    : plan.group
      ? [plan.group]
      : plan.plans;
  const ids = source.flatMap((p) => p.generated.map((g) => g.exercise.id));
  return [...new Set(ids)];
}

/** The groups to render, whichever path produced them. */
function groupsOf(plan: AdaptiveProposeResponse | null): AdaptiveGroupPlan[] {
  if (!plan) return [];
  if (plan.groups.length) return plan.groups;
  return plan.group ? [plan.group] : [];
}

export default function AdaptivePage() {
  const t = useTranslations('adaptive');
  const tc = useTranslations('common');
  const classes = useClasses();
  const subjects = useSubjects();

  const [itemsPerStudent, setItemsPerStudent] = useState(8);
  const [allowGeneration, setAllowGeneration] = useState(true);
  const [mode, setMode] = useState<Mode>('per_student');
  const [nGroups, setNGroups] = useState(4);
  // Which common sheet's results this batch answers. Recorded as the sheet's
  // lineage, and the sheet the feedback notes are read from.
  const [sourceSheetId, setSourceSheetId] = useState<Uuid | ''>('');
  // A student the teacher has picked up, waiting for a group to drop into.
  const [carrying, setCarrying] = useState<string | null>(null);
  // Teacher overrides: student uid -> group index. The model does not know
  // everything about a class, and the partition is a proposal, not a verdict.
  const [moves, setMoves] = useState<Record<string, number>>({});
  const [feedbackJobId, setFeedbackJobId] = useState<Uuid | null>(null);
  const [plan, setPlan] = useState<AdaptiveProposeResponse | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busyExercise, setBusyExercise] = useState<Uuid | null>(null);
  const [sheetId, setSheetId] = useState<Uuid | null>(null);
  const [jobId, setJobId] = useState<Uuid | null>(null);
  // Which ids the SERVER says are approved. Not a local flag: the export gate
  // has to reflect a fact about the database, not about this browser tab.
  const [approvedIds, setApprovedIds] = useState<ReadonlySet<Uuid>>(new Set());

  const propose = useProposeAdaptive();
  const writeFeedback = useGenerateFeedback();
  const approveNotes = useApproveFeedback();
  const discardNote = useDiscardFeedback();
  const feedbackJob = useJob(feedbackJobId);
  // The notes are written by a worker, so nothing about the notes query itself
  // changes when the job lands: it has to poll while the job is in flight, or
  // the teacher keeps looking at the list as it was before they asked.
  const writing =
    writeFeedback.isPending ||
    (feedbackJobId != null &&
      feedbackJob.data?.status !== 'succeeded' &&
      feedbackJob.data?.status !== 'failed');
  const feedback = useFeedback(sourceSheetId || null, writing);
  const approve = useApproveAdaptive();
  const discard = useDiscardAdaptive();
  const regenerate = useRegenerateAdaptive();
  const editExercise = useUpdateExercise();
  const batch = useBatchAdaptive();
  const render = useRenderAdaptiveBatch();
  const job = useJob(jobId);
  // The rendered PDFs hang off the sheet, so the download links come from
  // re-reading it once the job reports success.
  const sheet = useSheet(job.data?.status === 'succeeded' ? sheetId : null);

  // The class and subject the shell is scoped to. This used to be
  // `classes.data[0]` with no picker anywhere on the screen, so a teacher with
  // more than one class could only ever generate adaptive sheets — the focal
  // deliverable — for whichever class sorted first.
  const tcode = useTranslations('errors.code');
  const scope = useScope();
  const classId = scope.classId ?? '';
  // The corrected common sheets this batch could answer.
  const sheets = useSheets(classId || undefined);
  const students = useStudents(classId || null);
  const rosterSize = Math.max(2, students.data?.length ?? 2);
  const subjectId = scope.subjectId ?? '';

  const pending = generatedIds(plan);
  const approved = pending.length > 0 && pending.every((id) => approvedIds.has(id));
  const groups = groupsOf(plan);

  /**
   * The membership of one group, after the teacher's moves.
   *
   * A move is stored as uid -> group index, and applied here rather than
   * mutating the plan: the proposal stays the server's answer, and what the
   * teacher changed is visible as a separate fact until it is exported.
   */
  const membersOf = (group: AdaptiveGroupPlan, index: number): string[] => {
    const movedOut = group.student_uids.filter(
      (uid) => moves[uid] === undefined || moves[uid] === index,
    );
    const movedIn = Object.entries(moves)
      .filter(([uid, target]) => target === index && !group.student_uids.includes(uid))
      .map(([uid]) => uid);
    return [...movedOut, ...movedIn].sort();
  };

  // The notes as they stand now, by student, so the batch can carry them.
  const notes = feedback.data ?? [];
  const noteByStudent = new Map(notes.map((n) => [n.student_id, n]));
  const pendingNotes = notes.filter((n) => n.approved_at == null);

  /**
   * The plans to export, carrying each student's group label after any move
   * and whichever feedback note now exists for them.
   *
   * The note has to be re-attached here rather than trusted from the propose
   * response: `propose` runs BEFORE the teacher asks for feedback (the panel
   * only appears once a plan exists), so the `feedback_id` it returned is
   * always the state of the world one step ago. Exporting that would bind no
   * note at all, `build_feedback_data` would find none, and the approved
   * feedback would be dropped from the batch with nothing said about it.
   */
  const plansForExport = (): AdaptiveStudentPlan[] => {
    if (!plan) return [];
    const withNote = (p: AdaptiveStudentPlan): AdaptiveStudentPlan => ({
      ...p,
      feedback_id: noteByStudent.get(p.student_id)?.id ?? p.feedback_id ?? null,
    });
    if (!groups.length) return plan.plans.map(withNote);
    const labelByUid = new Map<string, { label: string; index: number }>();
    groups.forEach((group, index) => {
      for (const uid of membersOf(group, index)) {
        labelByUid.set(uid, { label: group.label, index: index + 1 });
      }
    });
    // A moved student takes the receiving group's ITEMS as well as its label:
    // a sheet headed "Groupe 3" holding group 1's exercises is the one outcome
    // a teacher would never expect from a move.
    const itemsByIndex = groups.map((g) => ({ retrieved: g.retrieved, generated: g.generated }));
    return plan.plans.map((p) => {
      const placed = labelByUid.get(p.student_uid);
      if (!placed) return withNote(p);
      const items = itemsByIndex[placed.index - 1];
      return {
        ...withNote(p),
        group_label: placed.label,
        group_index: placed.index,
        retrieved: items.retrieved,
        generated: items.generated,
      };
    });
  };

  const forget = (exerciseId: Uuid) =>
    setApprovedIds((current) => {
      const next = new Set(current);
      next.delete(exerciseId);
      return next;
    });

  /* --------------------------------------------------------------- state */
  if (classes.isError || subjects.isError) {
    return (
      <ErrorState
        title={t('loadError.title')}
        description={t('loadError.body')}
        action={
          <Button
            variant="primary"
            onClick={() => {
              void classes.refetch();
              void subjects.refetch();
            }}
          >
            {t('retry')}
          </Button>
        }
      />
    );
  }

  /* ------------------------------------------------------------- actions */
  function replaceProposal(replacedId: Uuid, replacement: ExerciseProposal | null) {
    setPlan((current) => {
      if (!current) return current;
      const swap = (list: ExerciseProposal[]) =>
        list.flatMap((item) =>
          item.exercise.id === replacedId ? (replacement ? [replacement] : []) : [item],
        );
      return {
        ...current,
        plans: current.plans.map((p) => ({ ...p, generated: swap(p.generated) })),
        group: current.group
          ? { ...current.group, generated: swap(current.group.generated) }
          : null,
      };
    });
  }

  function patchStatement(exerciseId: Uuid, statement: string) {
    setPlan((current) => {
      if (!current) return current;
      const edit = (list: ExerciseProposal[]) =>
        list.map((item) =>
          item.exercise.id === exerciseId
            ? { ...item, exercise: { ...item.exercise, statement } }
            : item,
        );
      return {
        ...current,
        plans: current.plans.map((p) => ({ ...p, generated: edit(p.generated) })),
        group: current.group ? { ...current.group, generated: edit(current.group.generated) } : null,
      };
    });
  }

  const handleEdit = (exerciseId: Uuid, statement: string) => {
    setBusyExercise(exerciseId);
    editExercise.mutate(
      { exerciseId, update: { statement } },
      {
        onSuccess: () => patchStatement(exerciseId, statement),
        onSettled: () => setBusyExercise(null),
      },
    );
  };

  const handleRegenerate = (exerciseId: Uuid) => {
    setBusyExercise(exerciseId);
    regenerate.mutate(
      { exercise_id: exerciseId },
      {
        // Replaces in place. The old id is gone server-side (discarded), so
        // leaving it in the list would export an item that cannot be printed.
        onSuccess: (result) => {
          forget(exerciseId);
          replaceProposal(exerciseId, result.proposal);
        },
        onSettled: () => setBusyExercise(null),
      },
    );
  };

  const handleDiscard = (exerciseId: Uuid) => {
    setBusyExercise(exerciseId);
    discard.mutate(
      { exercise_ids: [exerciseId] },
      {
        onSuccess: () => {
          forget(exerciseId);
          replaceProposal(exerciseId, null);
        },
        onSettled: () => setBusyExercise(null),
      },
    );
  };

  const startExport = () => {
    if (!plan) return;
    setJobId(null);
    batch.mutate(
      {
        class_id: classId,
        subject_id: subjectId,
        title: t('title'),
        language: (plan.language ?? 'fr') as 'fr' | 'de' | 'en',
        plans: plansForExport(),
        source_sheet_id: sourceSheetId || null,
        group_count: groups.length || null,
      },
      {
        // Creating the sheet is not rendering it. The render call is what
        // returns the job to poll — chaining them here is the whole export.
        onSuccess: (created) => {
          setSheetId(created.id);
          render.mutate(created.id, { onSuccess: (queued) => setJobId(queued.id) });
        },
      },
    );
  };

  /* -------------------------------------------------------------- render */
  const generatedCount = plan?.generated_count ?? 0;
  const failures = plan?.failures ?? [];
  const exporting =
    batch.isPending ||
    render.isPending ||
    (job.data != null && job.data.status !== 'succeeded' && job.data.status !== 'failed');
  const exportFailed = batch.isError || render.isError || job.data?.status === 'failed';

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6">
        <h1>{t('title')}</h1>
        <p className="text-ink-500">{t('subtitle')}</p>
      </header>

      <Card className="mb-6">
        <Field label={t('itemsPerStudent')}>
          <Slider min={1} max={16} value={itemsPerStudent} onValueChange={setItemsPerStudent} />
        </Field>

        <div className="mt-4">
          <SegmentedControl
            label={t('mode')}
            value={mode}
            onValueChange={setMode}
            options={[
              { value: 'per_student', label: t('modePerStudent') },
              { value: 'group', label: t('modeGroup') },
            ]}
          />
          {mode === 'group' ? (
            <p className="mt-1 text-body-s text-ink-500">{t('modeGroupHelp')}</p>
          ) : null}
        </div>

        {/* How many personalised groups. The two ends of the range are the two
            modes that already existed: 1 is one shared sheet, roster-size is
            one sheet per student. */}
        {mode === 'group' ? (
          <div className="mt-4">
            <Field label={t('groupCount')} help={t('groupCountHelp')}>
              <Slider
                min={MIN_GROUPS}
                max={Math.max(MIN_GROUPS + 1, rosterSize)}
                value={nGroups}
                onValueChange={(value) => {
                  setNGroups(value);
                  // The partition is rebuilt from scratch, so a move recorded
                  // against the old one no longer means anything. Dropping it
                  // is honest; silently re-applying it would put a student in
                  // a group the teacher never looked at.
                  setMoves({});
                  setCarrying(null);
                }}
              />
            </Field>
            <p className="mt-1 text-body-s text-ink-500" role="status">
              {nGroups <= 1
                ? t('groupCountOne')
                : nGroups >= rosterSize
                  ? t('groupCountPerStudent')
                  : t('groupCountMany', { count: nGroups })}
            </p>
          </div>
        ) : null}

        {/* The common sheet this batch answers. Optional: without it the plans
            still target each student's gaps, there is simply no feedback to
            write and no lineage to record. */}
        <div className="mt-4">
          <Field label={t('sourceSheet')}>
            <Select
              value={sourceSheetId}
              onChange={(event) => setSourceSheetId(event.target.value as Uuid | '')}
            >
              <option value="">{tc('none')}</option>
              {(sheets.data ?? [])
                .filter((s) => s.id !== sheetId)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
            </Select>
          </Field>
        </div>

        <div className="mt-4">
          <Toggle
            label={t('allowGeneration')}
            description={t('allowGenerationHelp')}
            checked={allowGeneration}
            onCheckedChange={setAllowGeneration}
          />
        </div>

        <div className="mt-4">
          <Button
            variant="primary"
            loading={propose.isPending}
            busyLabel={t('preparing')}
            onClick={() =>
              propose.mutate(
                {
                  class_id: classId,
                  subject_id: subjectId,
                  student_ids: [],
                  items_per_student: itemsPerStudent,
                  allow_generation: allowGeneration,
                  group: mode === 'group' && nGroups <= 1,
                  n_groups: mode === 'group' ? nGroups : null,
                  source_sheet_id: sourceSheetId || null,
                  // No `language`: the sheet follows the source material, and
                  // the server reads that off the corpus. Sending the UI locale
                  // here is exactly the bug this comment exists to prevent.
                },
                {
                  onSuccess: (r) => {
                    setPlan(r);
                    setApprovedIds(new Set());
                    setSheetId(null);
                    setJobId(null);
                    setExpanded(new Set());
                    setMoves({});
                    setCarrying(null);
                  },
                },
              )
            }
          >
            {t('propose')}
          </Button>
        </div>
      </Card>

      {propose.isError ? (
        <ErrorState
          className="mb-4"
          title={t('proposeError.title')}
          description={t('proposeError.body')}
          // The API's `message` is its own English string, for the console
          // (`client.ts` says so). `apiErrorMessage` switches on `code` instead.
          details={apiErrorMessage(propose.error, tcode)}
          action={
            <Button variant="primary" onClick={() => propose.reset()}>
              {t('retry')}
            </Button>
          }
        />
      ) : null}

      {propose.isPending ? (
        <LoadingState shape="list" label={t('preparing')} rows={5} />
      ) : !plan ? (
        <EmptyState
          illustration={<IlloSummit />}
          title={t('empty.title')}
          description={t('empty.body')}
        />
      ) : (
        <>
          {generatedCount > 0 ? (
            <Card tint="warm" className="mb-4">
              <p className="text-body-s">{t('aiNotice')}</p>
              <p className="mt-2 text-body-s font-bold">
                {t('needsApproval', { count: generatedCount })}
              </p>
              {!approved ? (
                <>
                  <p className="mt-1 text-body-s">{t('notApprovedWarning')}</p>
                  <p className="mt-1 text-body-s">{t('reviewFirst')}</p>
                  <div className="mt-3">
                    {/* The single sanctioned accent action (F4). It writes:
                        approval is a server fact, not a checkbox in this tab. */}
                    <Button
                      variant="accent"
                      loading={approve.isPending}
                      busyLabel={t('approving')}
                      onClick={() =>
                        approve.mutate(
                          { exercise_ids: pending },
                          {
                            onSuccess: (result) =>
                              setApprovedIds(new Set(result.exercise_ids)),
                          },
                        )
                      }
                    >
                      {t('approveAll', { count: generatedCount })}
                    </Button>
                  </div>
                </>
              ) : (
                <p className="mt-2 text-body-s" role="status">
                  {t('approved')}
                </p>
              )}
            </Card>
          ) : null}

          {failures.length > 0 ? (
            <Panel className="mb-4" role="status">
              <p className="flex items-center gap-2 text-body-s font-bold">
                <IconWarning aria-hidden />
                {t('failuresTitle', { count: failures.length })}
              </p>
              <ul className="mt-2 flex list-none flex-col gap-1 p-0 text-body-s">
                {failures.map((failure) => (
                  <li key={`${failure.student_uid}-${failure.reason}`}>
                    {failureLine(t, failure)}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-body-s text-ink-500">{t('failureHint')}</p>
            </Panel>
          ) : null}

          {/* Per-student feedback. Queued rather than inline: it is one model
              call per student, which a request handler may not block on. */}
          {sourceSheetId ? (
            <Card tint="warm" className="mb-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-h3">{t('feedbackTitle')}</h2>
                  <p className="mt-2 max-w-prose text-body-s text-ink-700">{t('feedbackBody')}</p>
                </div>
                <AiBadge label={t('aiBadge')} />
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button
                  loading={writing}
                  busyLabel={t('feedbackGenerating')}
                  onClick={() =>
                    writeFeedback.mutate(
                      {
                        class_id: classId,
                        subject_id: subjectId,
                        source_sheet_id: sourceSheetId,
                      },
                      { onSuccess: (queued) => setFeedbackJobId(queued.id) },
                    )
                  }
                >
                  {t('feedbackGenerate')}
                </Button>
                {pendingNotes.length > 0 ? (
                  <Button
                    variant="primary"
                    loading={approveNotes.isPending}
                    busyLabel={t('approving')}
                    onClick={() =>
                      approveNotes.mutate({ feedback_ids: pendingNotes.map((n) => n.id) })
                    }
                  >
                    {t('feedbackApproveAll', { count: pendingNotes.length })}
                  </Button>
                ) : null}
              </div>

              {writeFeedback.isError || feedbackJob.data?.status === 'failed' ? (
                <p className="mt-3 text-body-s" role="status">
                  {t('feedbackError')}
                </p>
              ) : null}

              {pendingNotes.length > 0 ? (
                <p className="mt-3 text-body-s font-bold" role="status">
                  {t('feedbackPending', { count: pendingNotes.length })}
                </p>
              ) : null}

              {feedback.isLoading ? (
                <LoadingState className="mt-4" shape="list" label={tc('loading')} rows={3} />
              ) : notes.length === 0 ? (
                <p className="mt-4 text-body-s text-ink-500">{t('feedbackEmpty')}</p>
              ) : (
                <ul className="mt-4 flex list-none flex-col gap-3 p-0">
                  {notes.map((note) => (
                    <li key={note.id}>
                      <FeedbackNoteCard
                        note={note}
                        busy={approveNotes.isPending || discardNote.isPending}
                        onApprove={(id) => approveNotes.mutate({ feedback_ids: [id] })}
                        onDiscard={(id) => discardNote.mutate({ feedback_ids: [id] })}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          ) : null}

          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-h3">{t('targeting')}</h2>
            <Button
              variant="primary"
              leadingIcon={<IconDownload />}
              loading={exporting}
              busyLabel={t('exporting')}
              // Generated items must be approved before anything is printed.
              // The server refuses too; this only saves a round trip.
              disabled={(generatedCount > 0 && !approved) || pendingNotes.length > 0}
              onClick={startExport}
            >
              {t('exportBatch')}
            </Button>
          </div>

          {exportFailed ? (
            <ErrorState
              className="mb-4"
              title={t('exportError.title')}
              description={t('exportError.body')}
              details={
                batch.error || render.error
                  ? apiErrorMessage(batch.error ?? render.error, tcode)
                  : undefined
              }
              action={
                <Button variant="primary" onClick={startExport}>
                  {t('retry')}
                </Button>
              }
            />
          ) : null}

          {job.data?.status === 'succeeded' ? (
            <Panel className="mb-4" role="status">
              <p className="text-body-s">{t('batchReady')}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {sheet.data?.blank_pdf_url ? (
                  <a href={sheet.data.blank_pdf_url} className="no-underline">
                    <Button variant="primary" leadingIcon={<IconDownload />}>
                      {t('downloadBlank')}
                    </Button>
                  </a>
                ) : null}
                {sheet.data?.answer_key_pdf_url ? (
                  <a href={sheet.data.answer_key_pdf_url} className="no-underline">
                    <Button variant="secondary" leadingIcon={<IconDownload />}>
                      {t('downloadAnswerKey')}
                    </Button>
                  </a>
                ) : null}
                {/* The third document. Separate from the blank and the key
                    because a feedback page must never enter the graded
                    pagination the scan detector counts. */}
                {sheet.data?.feedback_pdf_url ? (
                  <a href={sheet.data.feedback_pdf_url} className="no-underline">
                    <Button variant="secondary" leadingIcon={<IconDownload />}>
                      {t('downloadFeedback')}
                    </Button>
                  </a>
                ) : null}
              </div>
            </Panel>
          ) : null}

          {groups.length > 0 ? (
            <>
              {/* Moving a student is a teacher override of a computed
                  partition. The rule is a proposal; the person who knows the
                  child gets the last word. */}
              <p className="mb-2 min-h-11 text-body-s text-ink-500" role="status">
                {carrying ? t('moveSelected', { uid: carrying }) : t('moveHint')}
              </p>

              <ul className="mb-4 flex list-none flex-col gap-3 p-0">
                {groups.map((group, groupIndex) => {
                  const members = membersOf(group, groupIndex);
                  return (
                    <li key={group.label || groupIndex}>
                      <Panel>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <h3 className="text-h3">{group.label || t('groupTitle')}</h3>
                          <Badge variant="info">
                            {t('groupMembers', { count: members.length })}
                          </Badge>
                        </div>

                        <ul className="mt-3 flex list-none flex-wrap gap-2 p-0">
                          {members.map((uid) => (
                            <li key={uid}>
                              <Button
                                size="sm"
                                variant={carrying === uid ? 'primary' : 'secondary'}
                                aria-pressed={carrying === uid}
                                onClick={() => setCarrying(carrying === uid ? null : uid)}
                              >
                                <span data-numeric>{uid}</span>
                              </Button>
                            </li>
                          ))}
                        </ul>

                        {carrying && !members.includes(carrying) ? (
                          <div className="mt-3">
                            <Button
                              size="sm"
                              onClick={() => {
                                setMoves((current) => ({ ...current, [carrying]: groupIndex }));
                                setCarrying(null);
                              }}
                            >
                              {t('moveHere', { uid: carrying })}
                            </Button>
                          </div>
                        ) : null}

                        <ul className="mt-3 flex list-none flex-col gap-3 p-0">
                          {[...group.retrieved, ...group.generated].map((proposal, index) => (
                            <AdaptiveItem
                              key={proposal.exercise.id}
                              proposal={proposal}
                              number={index + 1}
                              forStudentUids={
                                group.items.find((i) => i.exercise_id === proposal.exercise.id)
                                  ?.for_student_uids
                              }
                              busy={busyExercise === proposal.exercise.id}
                              onEdit={handleEdit}
                              onRegenerate={handleRegenerate}
                              onDiscard={handleDiscard}
                            />
                          ))}
                        </ul>
                      </Panel>
                    </li>
                  );
                })}
              </ul>
            </>
          ) : (
            <ul className="flex list-none flex-col gap-3 p-0">
              {plan.plans.map((p) => {
                const items = [...p.retrieved, ...p.generated];
                const open = expanded.has(p.student_id);
                return (
                  <li key={p.student_id}>
                    <Panel>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        {/* The UID, not the name: this is what is printed and
                            what reaches a model. */}
                        <span className="mono font-bold" data-numeric>
                          {p.student_uid}
                        </span>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="info">
                            {t('retrieved')} · {p.retrieved.length}
                          </Badge>
                          {p.generated.length > 0 ? (
                            <AiBadge label={`${t('aiBadge')} · ${p.generated.length}`} size="sm" />
                          ) : null}
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-expanded={open}
                            onClick={() =>
                              setExpanded((current) => {
                                const next = new Set(current);
                                if (next.has(p.student_id)) next.delete(p.student_id);
                                else next.add(p.student_id);
                                return next;
                              })
                            }
                          >
                            {open ? t('hideItems') : t('showItems', { count: items.length })}
                          </Button>
                        </div>
                      </div>

                      {p.targeted_competency_ids.length > 0 ? (
                        <ul className="mt-2 flex list-none flex-wrap gap-1 p-0">
                          {p.targeted_competency_ids.slice(0, 6).map((id) => (
                            <li key={id}>
                              <ConceptTag code={id.slice(0, 8)} />
                            </li>
                          ))}
                        </ul>
                      ) : null}

                      {open ? (
                        <ul className="mt-3 flex list-none flex-col gap-3 p-0">
                          {items.map((proposal, index) => (
                            <AdaptiveItem
                              key={proposal.exercise.id}
                              proposal={proposal}
                              number={index + 1}
                              busy={busyExercise === proposal.exercise.id}
                              onEdit={handleEdit}
                              onRegenerate={handleRegenerate}
                              onDiscard={handleDiscard}
                            />
                          ))}
                        </ul>
                      ) : null}
                    </Panel>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
      <p className="sr-only">{tc('loading')}</p>
    </div>
  );
}

function failureLine(
  t: ReturnType<typeof useTranslations<'adaptive'>>,
  failure: AdaptiveGenerationFailure,
): string {
  const uid = failure.student_uid || '—';
  switch (failure.reason) {
    case 'pii_gate':
      return t('failurePiiGate', { uid });
    case 'provider_error':
      return t('failureProvider', { uid });
    case 'unparsable_response':
      return t('failureUnparsable', { uid });
    default:
      return t('failureIncomplete', {
        uid,
        produced: failure.produced,
        requested: failure.requested,
      });
  }
}
