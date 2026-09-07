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
  Slider,
  Toggle,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useScope } from '@/lib/scope';
import { apiErrorMessage } from '@/lib/api/error-message';

import { AdaptiveItem } from '@/components/AdaptiveItem';
import {
  useApproveAdaptive,
  useBatchAdaptive,
  useClasses,
  useDiscardAdaptive,
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
  AdaptiveProposeResponse,
  ExerciseProposal,
  Uuid,
} from '@/lib/api/types';

type Mode = 'per_student' | 'group';

/** Every generated exercise in a plan, in the order the teacher sees them. */
function generatedIds(plan: AdaptiveProposeResponse | null): Uuid[] {
  if (!plan) return [];
  const source = plan.group ? [plan.group] : plan.plans;
  const ids = source.flatMap((p) => p.generated.map((g) => g.exercise.id));
  return [...new Set(ids)];
}

export default function AdaptivePage() {
  const t = useTranslations('adaptive');
  const tc = useTranslations('common');
  const classes = useClasses();
  const subjects = useSubjects();

  const [itemsPerStudent, setItemsPerStudent] = useState(8);
  const [allowGeneration, setAllowGeneration] = useState(true);
  const [mode, setMode] = useState<Mode>('per_student');
  const [plan, setPlan] = useState<AdaptiveProposeResponse | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busyExercise, setBusyExercise] = useState<Uuid | null>(null);
  const [sheetId, setSheetId] = useState<Uuid | null>(null);
  const [jobId, setJobId] = useState<Uuid | null>(null);
  // Which ids the SERVER says are approved. Not a local flag: the export gate
  // has to reflect a fact about the database, not about this browser tab.
  const [approvedIds, setApprovedIds] = useState<ReadonlySet<Uuid>>(new Set());

  const propose = useProposeAdaptive();
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
  const subjectId = scope.subjectId ?? '';

  const pending = generatedIds(plan);
  const approved = pending.length > 0 && pending.every((id) => approvedIds.has(id));

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
        plans: plan.plans,
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
                  group: mode === 'group',
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

          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-h3">{t('targeting')}</h2>
            <Button
              variant="primary"
              leadingIcon={<IconDownload />}
              loading={exporting}
              busyLabel={t('exporting')}
              // Generated items must be approved before anything is printed.
              // The server refuses too; this only saves a round trip.
              disabled={generatedCount > 0 && !approved}
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
              </div>
            </Panel>
          ) : null}

          {plan.group ? (
            <Panel className="mb-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-h3">{t('groupTitle')}</h3>
                <Badge variant="info">
                  {t('groupFor', {
                    count: plan.group.student_uids.length,
                    total: plan.plans.length,
                  })}
                </Badge>
              </div>
              <p className="mt-1 text-body-s text-ink-500" data-numeric>
                {plan.group.student_uids.join(' · ')}
              </p>
              <ul className="mt-3 flex list-none flex-col gap-3 p-0">
                {[...plan.group.retrieved, ...plan.group.generated].map((proposal, index) => (
                  <AdaptiveItem
                    key={proposal.exercise.id}
                    proposal={proposal}
                    number={index + 1}
                    forStudentUids={
                      plan.group?.items.find((i) => i.exercise_id === proposal.exercise.id)
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
