'use client';

import {
  AiBadge,
  Badge,
  Button,
  Card,
  Checkbox,
  ConceptTag,
  EmptyState,
  ErrorState,
  Field,
  IconDownload,
  IconPlus,
  IconWarning,
  IlloSummit,
  LoadingState,
  Panel,
  ProgressRing,
  SegmentedControl,
  Select,
  Slider,
  Spinner,
  Toggle,
  useToast,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useRouter } from '@/i18n/navigation';
import { discardAdaptive as discardAdaptiveNow } from '@/lib/api/endpoints';
import { useFormatters } from '@/lib/format';
import { useScope } from '@/lib/scope';
import { apiErrorMessage } from '@/lib/api/error-message';
import { loadRun, recentRuns, rememberRun, saveRun, type RecentRun } from '@/lib/adaptive-session';

import { AdaptiveItem } from '@/components/AdaptiveItem';
import { AddExerciseModal } from '@/components/sheet-builder/AddExerciseModal';
import { FeedbackNoteCard } from '@/components/FeedbackNoteCard';
import {
  useApproveAdaptive,
  useApproveFeedback,
  useBatchAdaptive,
  useDiscardFeedback,
  useFeedback,
  useGenerateFeedback,
  useClasses,
  useCurriculumTree,
  useDiscardAdaptive,
  useSheets,
  useClass,
  useAdaptiveProposal,
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
  ApiLocale,
  ExerciseOut,
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

/** Long enough to notice the row vanish and change your mind; short enough
 *  that nobody is waiting on it. */
const DISCARD_UNDO_MS = 8000;

export default function AdaptivePage() {
  const t = useTranslations('adaptive');
  const tc = useTranslations('common');
  const fmt = useFormatters();
  const classes = useClasses();
  const subjects = useSubjects();

  const [itemsPerStudent, setItemsPerStudent] = useState(8);
  const [allowGeneration, setAllowGeneration] = useState(true);
  const [mode, setMode] = useState<Mode>('per_student');
  const [nGroups, setNGroups] = useState(4);
  // A second opinion on the partition, never the only one.
  const [llmGrouping, setLlmGrouping] = useState(false);
  // Which common sheet's results this batch answers. Recorded as the sheet's
  // lineage, and the sheet the feedback notes are read from.
  const [sourceSheetId, setSourceSheetId] = useState<Uuid | ''>('');
  /**
   * Further sheets whose corrected results justify this batch, beyond the
   * principal one.
   *
   * `AdaptiveBatchRequest` has carried `source_sheet_ids` since the backend pass
   * and the builder only ever sent the singular, while the sheet detail screen
   * rendered the plural lineage complete with a "Principal" chip — so the product
   * displayed a shape it could not produce (G15). The API's own reason for the
   * plural is the case this control exists for: a reprise may answer a test AND
   * the worksheets whose gaps it revisits, and `source_sheet_id` alone can only
   * name one of them (D70).
   *
   * Kept separate from `sourceSheetId` rather than folded into one list, because
   * the two are not the same fact: the principal becomes `Sheet.derived_from_id`
   * and is what the feedback notes are read from. The request sends the principal
   * first, which is the order the API documents.
   */
  const [alsoAnswers, setAlsoAnswers] = useState<ReadonlySet<Uuid>>(() => new Set());
  // A student the teacher has picked up, waiting for a group to drop into.
  const [carrying, setCarrying] = useState<string | null>(null);
  // Teacher overrides: student uid -> group index. The model does not know
  // everything about a class, and the partition is a proposal, not a verdict.
  const [moves, setMoves] = useState<Record<string, number>>({});
  const [feedbackJobId, setFeedbackJobId] = useState<Uuid | null>(null);
  /**
   * One pupil's plan, being built again after it failed.
   *
   * The failures panel listed each pupil the model could not plan for and offered
   * nothing to do about it: the only remedy was re-proposing the whole class,
   * which spends a provider call per pupil and throws away every group move and
   * discard the teacher has made since (G17).
   *
   * Its own job chain, deliberately, rather than reusing the main one. The main
   * chain's effect assigns `setPlan(proposal.data)` wholesale, so routing a
   * one-pupil proposal through it would replace the entire plan with a proposal
   * containing exactly one child.
   */
  const [retryFor, setRetryFor] = useState<Uuid | null>(null);
  const [retryJobId, setRetryJobId] = useState<Uuid | null>(null);
  // The planning runs in the worker, so the screen holds a job id and reads the
  // proposal back once it lands — the same shape as the feedback and export
  // chains further down this file.
  //
  // The id lives in the URL rather than in state, which is the whole of the
  // recoverability fix: `useState` meant that closing the laptop between
  // pressing Proposer and reading the result lost the only handle on a proposal
  // that is sitting finished in the database. The scan flow has always done it
  // this way (`scans/new` redirects to `/scans/{id}?job={jobId}`).
  //
  // `replace`, not `push`: a proposal is not a place in the history, and a
  // teacher pressing Back after Proposer means "leave", not "unstart".
  const searchParams = useSearchParams();
  const router = useRouter();
  const proposeJobId = (searchParams.get('job') as Uuid | null) ?? null;
  const setProposeJobId = useCallback(
    (id: Uuid | null) => {
      // Every other parameter is somebody else's: the scope (class, subject)
      // is sticky and lives here too, and dropping it would reset the screen.
      const next = new URLSearchParams(searchParams.toString());
      if (id) next.set('job', id);
      else next.delete('job');
      const query = next.toString();
      router.replace(query ? `/adaptive?${query}` : '/adaptive');
    },
    [router, searchParams],
  );
  const [plan, setPlan] = useState<AdaptiveProposeResponse | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busyExercise, setBusyExercise] = useState<Uuid | null>(null);
  // Which plan the "add" modal is filling. A number is a group index; a string
  // is a student uid. Null closes it.
  const [addingTo, setAddingTo] = useState<number | string | null>(null);
  const [sheetId, setSheetId] = useState<Uuid | null>(null);
  const [jobId, setJobId] = useState<Uuid | null>(null);
  // Which ids the SERVER says are approved. Not a local flag: the export gate
  // has to reflect a fact about the database, not about this browser tab.
  const [approvedIds, setApprovedIds] = useState<ReadonlySet<Uuid>>(new Set());

  // Discards waiting out their undo window: id -> the timer that will send it,
  // and the plan to put back if the teacher changes their mind.
  const pendingDiscards = useRef(
    new Map<Uuid, { timer: number; snapshot: AdaptiveProposeResponse | null }>(),
  );
  const { toast } = useToast();

  // Leaving the screen sends them. A discard the teacher did not undo is a
  // discard they meant, and dropping it on unmount would put the exercise back
  // in circulation without anyone deciding that.
  useEffect(() => {
    const pending = pendingDiscards.current;
    return () => {
      const ids = [...pending.keys()];
      for (const entry of pending.values()) window.clearTimeout(entry.timer);
      pending.clear();
      // The endpoint directly, not the mutation: a react-query mutation
      // started by a component that is unmounting has nowhere to report back
      // to. Nothing here needs a result — the screen is gone.
      if (ids.length > 0) void discardAdaptiveNow({ exercise_ids: ids }).catch(() => {});
    };
    // Mount/unmount only: the flush must see the map as it stands when the
    // screen goes away, and the ref is stable by construction.
  }, []);

  const propose = useProposeAdaptive();
  const proposeJob = useJob(proposeJobId);
  const proposeSucceeded = proposeJob.data?.status === 'succeeded';
  const proposal = useAdaptiveProposal(proposeSucceeded ? proposeJobId : null);
  // Busy from the click until the proposal is in hand: the mutation, the job,
  // and the read that follows it are one wait as far as the teacher is
  // concerned, and three spinners in a row would say otherwise.
  // What the job says about itself, for the ring and the words above it.
  const proposeProgress = proposeJob.data?.progress ?? 0;
  const proposeQueued = (proposeJob.data?.status ?? 'queued') === 'queued';
  const proposing =
    propose.isPending ||
    (proposeJobId != null &&
      proposeJob.data?.status !== 'succeeded' &&
      proposeJob.data?.status !== 'failed') ||
    (proposeSucceeded && proposal.isPending);

  // Copied into local state rather than read straight from the query: an edit,
  // a regeneration or a discard rewrites the plan in place, and the query holds
  // a megabyte it would be pointless to re-fetch to learn that.
  useEffect(() => {
    if (proposal.data) setPlan(proposal.data);
  }, [proposal.data]);

  // What the teacher changed about this proposal, which the server has not been
  // told about: the group moves, and the ids of an export already started.
  // Keyed by job id, so two runs cannot read each other's overrides.
  //
  // NOT `approvedIds`. See the note where it is declared: approval is a fact
  // about the database and the export gate reads it, so restoring it from a
  // tab's storage could open that gate on nobody's authority. A recovered run
  // shows its generated exercises as unapproved until the server says
  // otherwise — safe, and one click to put right. Making it *true* on recovery
  // needs a read the API does not have: the stored proposal is a payload
  // snapshot (`AdaptiveProposal.payload`), so the `approved_at` inside it is
  // frozen at proposal time, and there is no "which of these ids are approved"
  // endpoint to ask instead.
  useEffect(() => {
    if (!proposeJobId) return;
    const run = loadRun(proposeJobId);
    setMoves(run.moves);
    setSheetId(run.sheetId);
    setJobId(run.jobId);
  }, [proposeJobId]);

  useEffect(() => {
    if (!proposeJobId) return;
    saveRun(proposeJobId, { moves, sheetId, jobId });
  }, [proposeJobId, moves, sheetId, jobId]);
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
  const retryJob = useJob(retryJobId);
  const retryProposal = useAdaptiveProposal(
    retryJob.data?.status === 'succeeded' ? retryJobId : null,
  );
  const retryFailed = retryJob.data?.status === 'failed' || propose.isError;

  /**
   * Merge one pupil's fresh plan into the working copy.
   *
   * Merged, never assigned: everything else on screen — the other pupils' plans,
   * the groups, the teacher's moves and discards — has to survive a retry that
   * concerns one child. Replaced in place when they already had an entry, appended
   * when they did not, which is the usual case since a failure means nothing was
   * produced for them.
   */
  useEffect(() => {
    const fresh = retryProposal.data;
    const student = retryFor;
    if (!fresh || !student) return;
    setPlan((current) => {
      if (!current) return current;
      const incoming = fresh.plans.find((p) => p.student_id === student);
      // It can fail again, and saying so beats silently dropping the row.
      const stillFailed = fresh.failures.find((f) => f.student_id === student);
      const had = current.plans.some((p) => p.student_id === student);
      return {
        ...current,
        plans: incoming
          ? had
            ? current.plans.map((p) => (p.student_id === student ? incoming : p))
            : [...current.plans, incoming]
          : current.plans,
        failures: [
          ...current.failures.filter((f) => f.student_id !== student),
          ...(stillFailed ? [stillFailed] : []),
        ],
      };
    });
    setRetryFor(null);
    setRetryJobId(null);
  }, [retryProposal.data, retryFor]);

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
  // `ClassOut.student_count`, not the roster. This slider needs one integer,
  // and `useStudents` answers with every child's first name, last name, uid
  // and class codes — on the one screen whose entire design keeps names away
  // from a model (`alppy/ai/scrub.py`, and the notes below render
  // `student_uid`). Fetching the names here to read `.length` put them in the
  // page's cache for no reason at all.
  const klass = useClass(classId || null);
  // The plan carries competency IDS; the tree is what turns them into the codes
  // a teacher recognises. Without it this screen printed `a3f9c012` — the first
  // eight characters of a UUID — in a `ConceptTag`, which is the component
  // whose entire job is to show a curriculum code (F16). The sheet detail page
  // already fetches this, for the same reason and with the same one request.
  const rosterSize = Math.max(2, klass.data?.student_count ?? 2);
  const subjectId = scope.subjectId ?? '';
  const curriculum = useCurriculumTree(classId || null, { subjectId: subjectId || undefined });

  /** `competency_id` -> the code printed on the programme. */
  const competencyCode = new Map(
    (curriculum.data?.branches ?? [])
      .flatMap((branch) => branch.competences)
      .map((competence) => [competence.competency_id, competence.code]),
  );

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
  /** Ask for one pupil's plan again, on its own job. */
  function retryStudent(studentId: Uuid) {
    setRetryFor(studentId);
    propose.mutate(
      {
        class_id: classId,
        subject_id: subjectId,
        // The whole point: scoped to one child. `student_ids` has been on the
        // request type all along and nothing ever sent a non-empty one.
        student_ids: [studentId],
        items_per_student: itemsPerStudent,
        allow_generation: allowGeneration,
        // Never group a retry: grouping partitions a CLASS, and a partition of one
        // pupil is not a partition. The pupil keeps whatever group the teacher
        // already put them in — `moves` is keyed by uid and is untouched by this.
        group: false,
        n_groups: null,
        llm_grouping: false,
        source_sheet_id: sourceSheetId || null,
      },
      {
        onSuccess: (job) => setRetryJobId(job.id),
        onError: () => setRetryFor(null),
      },
    );
  }

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
        // `groups` was missing here, so in N-group mode a regenerate or a
        // discard changed the server and nothing on screen — the list the
        // screen renders is `groups` whenever there is more than one.
        groups: current.groups.map((g) => ({ ...g, generated: swap(g.generated) })),
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
        group: current.group
          ? { ...current.group, generated: edit(current.group.generated) }
          : null,
        groups: current.groups.map((g) => ({ ...g, generated: edit(g.generated) })),
      };
    });
  }

  /**
   * A teacher-written exercise, appended to one plan before export.
   *
   * It lands in the corpus as `origin: 'teacher'`, which is deliberately
   * neither of the other two: no source page to audit against a book, and the
   * mandarin accent means "a model wrote this". So it needs no approval, and
   * the export gate is untouched by it.
   */
  function appendExercise(target: number | string, exercise: ExerciseOut) {
    const proposal: ExerciseProposal = {
      exercise,
      score: 1,
      // No source, no page, no similarity: the teacher wrote it just now, and
      // claiming a provenance it does not have is worse than an empty one.
      provenance: {
        source_id: null,
        source_filename: null,
        page: null,
        excerpt: null,
        similarity: null,
        reason: t('addedByTeacher'),
      },
    };
    setPlan((current) => {
      if (!current) return current;
      const isGroup = typeof target === 'number';
      return {
        ...current,
        plans: current.plans.map((p) =>
          (isGroup ? p.group_index === target + 1 : p.student_uid === target)
            ? { ...p, retrieved: [...p.retrieved, proposal] }
            : p,
        ),
        group:
          isGroup && target === 0 && current.group
            ? { ...current.group, retrieved: [...current.group.retrieved, proposal] }
            : current.group,
        groups: current.groups.map((g, index) =>
          isGroup && index === target
            ? {
                ...g,
                retrieved: [...g.retrieved, proposal],
                // Shared paper: the item is for everyone in the group, because
                // the teacher chose it for the group rather than for a gap.
                items: [...g.items, { exercise_id: exercise.id, for_student_uids: g.student_uids }],
              }
            : g,
        ),
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

  /**
   * Discard, with a window to take it back (F18).
   *
   * The server's discard is final — "they are never proposed or printed again"
   * — and there is no route that restores one. So the undo cannot reverse the
   * call; it has to precede it. The exercise leaves the screen at once, and
   * the request goes out when the toast expires.
   *
   * Nothing is inconsistent in between: the export builds from `plan`, which
   * has already dropped the item, so a teacher who exports inside the window
   * gets exactly what they see. What the deferred call decides is only whether
   * the exercise can be proposed again later.
   *
   * The snapshot is the whole plan rather than the one proposal, because
   * putting a proposal back where it came from means knowing which student's
   * list and which position — and the plan we already hold answers both
   * exactly.
   */
  const commitDiscard = (exerciseId: Uuid) => {
    const entry = pendingDiscards.current.get(exerciseId);
    if (!entry) return;
    window.clearTimeout(entry.timer);
    pendingDiscards.current.delete(exerciseId);
    discard.mutate({ exercise_ids: [exerciseId] });
  };

  const undoDiscard = (exerciseId: Uuid) => {
    const entry = pendingDiscards.current.get(exerciseId);
    if (!entry) return;
    window.clearTimeout(entry.timer);
    pendingDiscards.current.delete(exerciseId);
    setPlan(entry.snapshot);
  };

  const handleDiscard = (exerciseId: Uuid) => {
    const snapshot = plan;
    forget(exerciseId);
    replaceProposal(exerciseId, null);
    const timer = window.setTimeout(() => commitDiscard(exerciseId), DISCARD_UNDO_MS);
    pendingDiscards.current.set(exerciseId, { timer, snapshot });
    toast({
      title: t('discarded'),
      variant: 'default',
      duration: DISCARD_UNDO_MS,
      action: { label: tc('undo'), onClick: () => undoDiscard(exerciseId) },
    });
  };

  /** The lineage, principal first, or null when this batch answers nothing. */
  const sourceSheetIds = (): Uuid[] | null => {
    if (!sourceSheetId) return null;
    // The principal cannot also appear as further evidence, and the set is
    // filtered rather than trusted: a sheet can be deselected as principal after
    // being ticked below.
    const rest = [...alsoAnswers].filter((id) => id !== sourceSheetId);
    return [sourceSheetId as Uuid, ...rest];
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
        // Principal first: the API treats `source_sheet_id` as entry 0 of this
        // list, and the sheet screen renders entry 0 with the "Principal" chip.
        source_sheet_ids: sourceSheetIds(),
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

            {/* Off by default, and it says why. The deterministic rule is the
                one a teacher can state to a parent; an invalid or failed model
                answer falls straight back to it, so this is a second opinion
                rather than a replacement. */}
            {nGroups > 1 && nGroups < rosterSize ? (
              <div className="mt-3">
                <Toggle
                  label={t('llmGrouping')}
                  description={t('llmGroupingHelp')}
                  checked={llmGrouping}
                  onCheckedChange={(value) => {
                    setLlmGrouping(value);
                    setMoves({});
                    setCarrying(null);
                  }}
                />
              </div>
            ) : null}
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

        {/* Offered only once a principal sheet is chosen: "also answers" has no
            meaning without something to be further evidence FOR, and an empty
            checkbox list above an unset select would read as a second, redundant
            picker. */}
        {sourceSheetId ? (
          <fieldset className="mt-4 border-0 p-0">
            <legend className="text-label uppercase text-ink-700">{t('alsoAnswers')}</legend>
            <p className="mt-1 text-body-s text-ink-500">{t('alsoAnswersHelp')}</p>
            <div className="mt-2 flex flex-col gap-2">
              {(sheets.data ?? [])
                .filter((s) => s.id !== sheetId && s.id !== sourceSheetId)
                .map((s) => (
                  <Checkbox
                    key={s.id}
                    label={s.title}
                    checked={alsoAnswers.has(s.id)}
                    onChange={(event) => {
                      const { checked } = event.currentTarget;
                      setAlsoAnswers((current) => {
                        const next = new Set(current);
                        if (checked) next.add(s.id);
                        else next.delete(s.id);
                        return next;
                      });
                    }}
                  />
                ))}
            </div>
          </fieldset>
        ) : null}

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
            loading={proposing}
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
                  llm_grouping: mode === 'group' && llmGrouping,
                  source_sheet_id: sourceSheetId || null,
                  // No `language`: the sheet follows the source material, and
                  // the server reads that off the corpus. Sending the UI locale
                  // here is exactly the bug this comment exists to prevent.
                },
                {
                  onSuccess: (job) => {
                    // Remembered before anything else: this is the record that
                    // survives the tab being closed, and the id is the only
                    // handle on a proposal the worker is still building.
                    rememberRun(classId || null, job.id, new Date().toISOString());
                    setProposeJobId(job.id);
                    setPlan(null);
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

      {/* The teacher's own exercise. Reuses the sheet builder's modal: same
          form, same validation, same `origin: 'teacher'` row in the corpus —
          and the language comes from the SHEET, never `useLocale()`, because
          `Exercise.language` picks the printed V/F · R/F · T/F glyphs. */}
      {plan && subjectId ? (
        <AddExerciseModal
          open={addingTo !== null}
          onOpenChange={(open) => setAddingTo(open ? addingTo : null)}
          subjectId={subjectId}
          language={plan.language as ApiLocale}
          onCreated={(exercise) => {
            if (addingTo !== null) appendExercise(addingTo, exercise);
            setAddingTo(null);
          }}
        />
      ) : null}

      {propose.isError || proposeJob.data?.status === 'failed' || proposal.isError ? (
        <ErrorState
          className="mb-4"
          title={t('proposeError.title')}
          description={t('proposeError.body')}
          // The API's `message` is its own English string, for the console
          // (`client.ts` says so). `apiErrorMessage` switches on `code` instead.
          details={apiErrorMessage(propose.error ?? proposal.error, tcode)}
          action={
            <Button
              variant="primary"
              onClick={() => {
                propose.reset();
                setProposeJobId(null);
              }}
            >
              {t('retry')}
            </Button>
          }
        />
      ) : null}

      {proposing ? (
        <>
          {/* Twenty-four students is twenty-four sequential provider calls
              behind one 600-second timeout, and this said nothing about how
              far it had got for the whole of it (F13). `useJob` has always
              fetched `progress`; the scan screen has always drawn it. Same
              shape, same components.

              A ring only once there is something to report: one drawn at 0 is
              a meter saying "nothing has happened", which is both wrong and
              discouraging while a queue is still being picked up. */}
          <Panel className="mb-4 flex items-center gap-4" role="status" aria-live="polite">
            {proposeProgress > 0 ? (
              <ProgressRing
                value={proposeProgress}
                centre={fmt.percent(proposeProgress)}
                label={t('preparing')}
                size={56}
              />
            ) : (
              <Spinner size={32} className="shrink-0 text-primary-600" />
            )}
            <div className="min-w-0">
              <p className="text-body font-bold text-ink-900">
                {t(proposeQueued ? 'preparingQueued' : 'preparing')}
              </p>
              <p className="text-body-s text-ink-500">{t('preparingHelp')}</p>
            </div>
          </Panel>
          <LoadingState shape="list" label={t('preparing')} rows={5} />
        </>
      ) : !plan ? (
        <>
          <EmptyState
            illustration={<IlloSummit />}
            title={t('empty.title')}
            description={t('empty.body')}
          />
          {/* Somewhere to look for a run whose tab is gone. Rendered under the
              empty state because that is the screen a teacher lands on when
              they come back — the same screen that used to offer them nothing
              but a button that would rebuild what already exists. */}
          <RecentProposals classId={classId} onOpen={setProposeJobId} />
        </>
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
                            onSuccess: (result) => setApprovedIds(new Set(result.exercise_ids)),
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
              <ul className="mt-2 flex list-none flex-col gap-2 p-0 text-body-s">
                {failures.map((failure) => (
                  <li
                    key={`${failure.student_uid}-${failure.reason}`}
                    className="flex flex-wrap items-center justify-between gap-2"
                  >
                    <span className="min-w-0">{failureLine(t, failure)}</span>
                    {/* One pupil, one retry (G17). Re-proposing the whole class
                        is a provider call per child and discards every group move
                        and discard made since; this asks only for the pupil who
                        failed and merges the answer in. */}
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={retryFor === failure.student_id}
                      busyLabel={t('retryingStudent')}
                      disabled={retryFor !== null}
                      onClick={() => retryStudent(failure.student_id)}
                    >
                      {t('retryStudent')}
                    </Button>
                  </li>
                ))}
              </ul>
              {retryFailed ? (
                <p className="mt-2 text-body-s text-danger-600" role="alert">
                  {t('retryStudentFailed')}
                </p>
              ) : null}
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

              {/* Which rule produced the partition. The deterministic one is
                  the default and the fallback; when a model's answer was
                  accepted the teacher should know that is what they are looking
                  at, because they are the one who will have to justify it. */}
              <p className="mb-2 text-body-s text-ink-500">
                {plan.grouped_by_model ? t('groupedByModel') : t('groupedByRule')}
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

                        <div className="mt-3">
                          <Button
                            size="sm"
                            variant="secondary"
                            leadingIcon={<IconPlus />}
                            onClick={() => setAddingTo(groupIndex)}
                          >
                            {t('addExercise')}
                          </Button>
                        </div>
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
                          {/* A competency the tree does not name is not shown
                              as a UUID stump: the tag is for codes, and a
                              teacher reading `a3f9c012` learns nothing they
                              could act on. */}
                          {p.targeted_competency_ids
                            .slice(0, 6)
                            .map((id) => ({ id, code: competencyCode.get(id) }))
                            .filter((entry) => entry.code !== undefined)
                            .map((entry) => (
                              <li key={entry.id}>
                                <ConceptTag code={entry.code as string} />
                              </li>
                            ))}
                        </ul>
                      ) : null}

                      {/* Which evidence chose these competencies, and whether
                          it was all of it. "Targeted the sheet you corrected"
                          and "targeted the term so far" are different answers,
                          and the teacher is the one who has to defend the
                          sheet. */}
                      <p className="mt-2 text-body-s text-ink-500">
                        {t(`basis.${p.targeting_basis}`)}
                        {p.evidence_partial ? ` · ${t('evidencePartial')}` : null}
                      </p>

                      {open ? (
                        <>
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
                          <div className="mt-3">
                            <Button
                              size="sm"
                              variant="secondary"
                              leadingIcon={<IconPlus />}
                              onClick={() => setAddingTo(p.student_uid)}
                            >
                              {t('addExercise')}
                            </Button>
                          </div>
                        </>
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
    // Its own line, not folded into "unusable response": the cause is a
    // configured limit, and saying so is the difference between a teacher who
    // can act and one who retries forever.
    case 'truncated':
      return t('failureTruncated', { uid });
    default:
      return t('failureIncomplete', {
        uid,
        produced: failure.produced,
        requested: failure.requested,
      });
  }
}

/**
 * The last few differentiation runs started for this class, on this browser.
 *
 * Deliberately local. `GET /jobs?kind=propose_adaptive` exists and has no
 * caller, but it is scoped to the SCHOOL — `JobOut` carries no `class_id` —
 * so a server-side list would show a teacher that a colleague started a run at
 * 10:15, and could offer them a row that answers 404 when opened (correctly:
 * `read_proposal` gates on the class). Reading the ids back out of this
 * browser answers the case the finding is actually about — the laptop closed
 * between pressing Proposer and reading the result — without either problem.
 *
 * The gap this leaves, stated plainly: a run started on the classroom desktop
 * is not listed on the laptop at home. Closing that needs one field —
 * `class_id` on `JobOut` — and then this component reads the API instead.
 */
function RecentProposals({ classId, onOpen }: { classId: string; onOpen: (jobId: Uuid) => void }) {
  const t = useTranslations('adaptive');
  const fmt = useFormatters();
  // Read after mount: `localStorage` does not exist while this renders on the
  // server, and reading it during render would make the two disagree.
  const [runs, setRuns] = useState<RecentRun[]>([]);
  useEffect(() => setRuns(recentRuns(classId || null)), [classId]);

  if (runs.length === 0) return null;

  return (
    <Panel className="mt-4">
      <h2 className="mb-1 text-label uppercase text-ink-500">{t('recent.title')}</h2>
      <p className="mb-3 text-body-s text-ink-700">{t('recent.body')}</p>
      <ul className="flex flex-col gap-2">
        {runs.map((run) => (
          <li key={run.jobId}>
            <Button variant="ghost" onClick={() => onOpen(run.jobId)}>
              {fmt.dateTime(run.startedAt)}
            </Button>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
