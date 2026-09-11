'use client';

import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  IconChevronDown,
  IconChevronUp,
  IconClose,
  IconPlus,
  IconTrash,
  IlloCompass,
  LoadingState,
  SelectSurface,
} from '@alppy/ui';
import { ApiError } from '@/lib/api/client';
import { useLocale, useTranslations } from 'next-intl';
import { use, useState } from 'react';

import { ConfirmDestructive } from '@/components/ConfirmDestructive';
import {
  useAssignBranch,
  useClass,
  useClassTeachers,
  useColleagues,
  useDeclareBranch,
  useReorderBranches,
  useSubjects,
} from '@/lib/api/queries';
import { apiErrorMessage, requestIdOf } from '@/lib/api/error-message';
import type { ClassTeacherOut, SubjectOut, Uuid } from '@/lib/api/types';

/**
 * Who teaches which Branch in this class — the screen D57 deferred and D75
 * built the endpoints for.
 *
 * It is the ONE screen that reads `declared_subject_ids` (what the class
 * STUDIES) rather than `subject_ids` (what the caller TEACHES). Everywhere else
 * narrows to the reader's own branches, which is the point of strict isolation;
 * here the superset is the subject matter, and showing it is what makes a
 * branch nobody teaches visible at all. A class where history sits on the
 * programme with no teacher on it is a real state, and this is the only place
 * it can be seen or fixed.
 *
 * Two things it deliberately does not do. It shows no per-branch sheet count:
 * the API returns one on the refusal, not on `ClassOut`, and a number invented
 * client-side would be a promise the read path cannot keep. And it gives a
 * branch no colour, icon or tint (DC-colour-06, DC-colour-08) — the mandarin
 * accent means "a model wrote this" and nothing else, so a branch is named.
 */
export default function TeachingPage({ params }: { params: Promise<{ classId: string }> }) {
  const { classId } = use(params);
  const t = useTranslations('teaching');
  const tc = useTranslations('common');
  const tcode = useTranslations('errors.code');
  const ttree = useTranslations('tree');
  const locale = useLocale();

  const klass = useClass(classId);
  const teachers = useClassTeachers(classId);
  const subjects = useSubjects();
  const colleagues = useColleagues();

  const assign = useAssignBranch();
  const declare = useDeclareBranch();
  const reorder = useReorderBranches();

  // Which colleague each branch's picker is showing. Keyed by subject, because
  // one open picker shared by every panel would move the selection under the
  // teacher whenever they looked at a different branch.
  const [picked, setPicked] = useState<Record<string, Uuid>>({});
  const [toDeclare, setToDeclare] = useState<Uuid | ''>('');
  const [confirming, setConfirming] = useState<Uuid | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
  /**
   * Whether the refusal in the dialog is one that pressing again cannot get
   * past. `branch_holds_sheets` will answer the same way until the sheets
   * move, so the confirm goes cold; a network blip is worth another press and
   * leaves it live.
   */
  const [removeBlocked, setRemoveBlocked] = useState(false);

  const label = (subject: SubjectOut | undefined) =>
    subject?.labels?.[locale] ?? subject?.labels?.fr ?? subject?.key ?? '';

  const subjectById = (id: Uuid) => (subjects.data ?? []).find((s) => s.id === id);

  /**
   * The refusal is the only error on this screen that carries a number, and the
   * number is the whole message: "still holds 4 sheets" tells the teacher what
   * to do, "no longer possible in the current state" does not.
   */
  function removalMessage(caught: unknown): string {
    if (caught instanceof ApiError && caught.code === 'branch_holds_sheets') {
      return t('branchHoldsSheets', {
        count: Number(caught.details.sheet_count ?? 0),
        code: klass.data?.code ?? '',
      });
    }
    return apiErrorMessage(caught, tcode);
  }

  const isLoading =
    klass.isLoading || teachers.isLoading || subjects.isLoading || colleagues.isLoading;
  const isError = klass.isError || teachers.isError || subjects.isError || colleagues.isError;

  if (isLoading) return <LoadingState shape="list" label={tc('loading')} rows={3} />;

  if (isError) {
    return (
      <ErrorState
        title={t('error.title')}
        description={t('error.body')}
        requestId={requestIdOf(klass.error ?? teachers.error ?? subjects.error ?? colleagues.error)}
        action={
          <Button
            onClick={() => {
              void klass.refetch();
              void teachers.refetch();
              void subjects.refetch();
              void colleagues.refetch();
            }}
          >
            {tc('retry')}
          </Button>
        }
      />
    );
  }

  // The class's own order, not one teacher's — so it comes off the class in the
  // order the API sent it and is never re-sorted here.
  const declared = klass.data?.declared_subject_ids ?? [];
  const rows = teachers.data ?? [];
  const undeclared = (subjects.data ?? []).filter((s) => !declared.includes(s.id));

  const holders = (subjectId: Uuid): ClassTeacherOut[] =>
    rows.filter((row) => row.subject_ids.includes(subjectId));

  /** Whoever does not already hold this branch. Includes the signed-in teacher:
   *  `/colleagues` returns the whole staffroom, self included. */
  const addable = (subjectId: Uuid) =>
    (colleagues.data ?? []).filter((c) => !holders(subjectId).some((h) => h.teacher_id === c.id));

  function move(subjectId: Uuid, by: -1 | 1) {
    const from = declared.indexOf(subjectId);
    const to = from + by;
    if (from < 0 || to < 0 || to >= declared.length) return;
    const next = [...declared];
    next.splice(to, 0, ...next.splice(from, 1));
    setError(null);
    reorder.mutate(
      { classId, subjectIds: next },
      { onError: (caught) => setError(apiErrorMessage(caught, tcode)) },
    );
  }

  const confirmingSubject = confirming ? subjectById(confirming) : undefined;

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-4 flex flex-col gap-1">
        <h1>{t('heading', { code: klass.data?.code ?? '' })}</h1>
        <p className="text-ink-500">
          {t('summary', { branches: declared.length, teachers: rows.length })}
        </p>
      </header>

      {error ? (
        <p role="alert" className="mb-4 text-body-s font-semibold text-danger-600">
          {error}
        </p>
      ) : null}

      {declared.length === 0 ? (
        <Card>
          <EmptyState
            illustration={<IlloCompass />}
            title={t('empty.title')}
            description={t('empty.body')}
          />
        </Card>
      ) : (
        /* ONE Card — the class. Every branch inside it is a PANEL, because a
           branch is a subdivision of this class and not a separate object
           (DC-shape-01). Three cards here would flatten the hierarchy into
           three shadows of equal weight. */
        <Card className="mb-4 flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h2 className="text-h3">{t('branchesTitle')}</h2>
            <p className="text-body-s text-ink-500">{t('branchesHelp')}</p>
          </div>

          <ul className="flex flex-col gap-3">
            {declared.map((subjectId, index) => {
              const subject = subjectById(subjectId);
              const name = label(subject);
              const held = holders(subjectId);
              const canAdd = addable(subjectId);
              const chosen = picked[subjectId] ?? canAdd[0]?.id ?? '';

              return (
                <li key={subjectId} className="ard-panel flex flex-col gap-3">
                  {/* Two wrap units, and NO `min-w-0` on either. At 390 px the
                      arrows, the name, the key and "Retirer" do not fit on one
                      line: "Retirer" was clipped off the panel's right edge.
                      `min-w-0` was the wrong fix — a branch name is often a
                      single unbreakable word ("Mathématiques"), so letting the
                      title shrink below its min-content made it overflow ON TOP
                      of the key instead of pushing the button to a second row.
                      Refusing to shrink is what makes the wrap happen. */}
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="flex flex-1 items-center gap-2">
                      {/* Side by side, not stacked. A stacked pair fits the
                          header in 44px total but gives each arrow 22 — half
                          the 44 px floor this product holds itself to, on a
                          screen that is used on a phone. Two full-size targets
                          cost width, which this row has, rather than height. */}
                      <div className="flex shrink-0 items-center">
                        <button
                          type="button"
                          className="ard-btn w-11 px-0"
                          data-variant="ghost"
                          title={t('moveUp')}
                          aria-label={t('moveUp')}
                          disabled={index === 0 || reorder.isPending}
                          onClick={() => move(subjectId, -1)}
                        >
                          <IconChevronUp size={20} />
                        </button>
                        <button
                          type="button"
                          className="ard-btn w-11 px-0"
                          data-variant="ghost"
                          title={t('moveDown')}
                          aria-label={t('moveDown')}
                          disabled={index === declared.length - 1 || reorder.isPending}
                          onClick={() => move(subjectId, 1)}
                        >
                          <IconChevronDown size={20} />
                        </button>
                      </div>
                      <h3 className="text-h3">{name}</h3>
                      {/* The join key, as data: outline only, mono, never
                          coloured — the same treatment official curriculum
                          codes get everywhere else. */}
                      <span className="ard-concept-tag shrink-0">{subject?.key}</span>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="shrink-0"
                      title={t('removeBranch', { branch: name })}
                      onClick={() => {
                        setRemoveError(null);
                        setRemoveBlocked(false);
                        setConfirming(subjectId);
                      }}
                    >
                      <IconTrash size={18} />
                      {t('remove')}
                    </Button>
                  </div>

                  {held.length === 0 ? (
                    /* Not colour alone: the chip is named "Personne" and the
                       sentence beside it says what the state means. */
                    <div className="flex items-start gap-3 rounded-sm bg-surface-2 px-3 py-2">
                      <span className="ard-chip" data-variant="warn">
                        {t('nobody')}
                      </span>
                      <p className="flex-1 text-body-s text-ink-700">{t('nobodyHelp')}</p>
                    </div>
                  ) : (
                    <ul className="flex flex-col gap-2">
                      {held.map((row) => (
                        <li
                          key={row.teacher_id}
                          className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1 rounded-sm bg-surface-2 py-1 pl-3 pr-2"
                        >
                          <span className="flex-1 font-semibold">
                            {row.first_name} {row.last_name}
                          </span>
                          {/* Written, never a colour: the head teacher is a
                              role, and a violet pill would read as an action
                              (DC-colour-05). */}
                          {row.is_head ? (
                            <span className="ard-chip shrink-0">{t('headTeacher')}</span>
                          ) : null}
                          <button
                            type="button"
                            className="ard-btn w-11 px-0"
                            data-variant="ghost"
                            title={t('removeTeacher', {
                              name: `${row.first_name} ${row.last_name}`,
                              branch: name,
                            })}
                            aria-label={t('removeTeacher', {
                              name: `${row.first_name} ${row.last_name}`,
                              branch: name,
                            })}
                            disabled={assign.isPending}
                            onClick={() => {
                              setError(null);
                              assign.mutate(
                                {
                                  classId,
                                  teacherId: row.teacher_id,
                                  subjectId,
                                  assign: false,
                                },
                                { onError: (caught) => setError(apiErrorMessage(caught, tcode)) },
                              );
                            }}
                          >
                            <IconClose size={18} />
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}

                  {canAdd.length > 0 ? (
                    <div className="flex flex-wrap items-center gap-2">
                      {/* Full width on a phone, sharing the row above it: the
                          picker plus "Ajouter" cut the colleague's name down to
                          "San…", which is not a name a teacher can pick by. */}
                      <SelectSurface
                        className="w-full rounded-md sm:w-auto sm:flex-1"
                        label={t('colleague')}
                        value={chosen}
                        onChange={(value) =>
                          setPicked((prev) => ({ ...prev, [subjectId]: value as Uuid }))
                        }
                        options={canAdd.map((c) => ({
                          value: c.id,
                          label: `${c.first_name} ${c.last_name}`,
                        }))}
                      >
                        <span className="flex min-h-11 items-center gap-2 rounded-md border border-line bg-surface px-3">
                          <span className="text-label font-semibold uppercase tracking-label text-ink-500">
                            {t('colleague')}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-body-s font-semibold text-ink-900">
                            {(() => {
                              const who = canAdd.find((c) => c.id === chosen);
                              return who ? `${who.first_name} ${who.last_name}` : t('choose');
                            })()}
                          </span>
                          <IconChevronDown size={16} className="shrink-0 text-ink-500" />
                        </span>
                      </SelectSurface>
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={!chosen || assign.isPending}
                        onClick={() => {
                          setError(null);
                          assign.mutate(
                            { classId, teacherId: chosen as Uuid, subjectId, assign: true },
                            {
                              onError: (caught) => setError(apiErrorMessage(caught, tcode)),
                              onSuccess: () =>
                                setPicked((prev) => {
                                  const next = { ...prev };
                                  delete next[subjectId];
                                  return next;
                                }),
                            },
                          );
                        }}
                      >
                        <IconPlus size={18} />
                        {t('add')}
                      </Button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </Card>
      )}

      {/* Declaring a branch is a different act from staffing one, so it is its
          own object rather than a fourth panel inside the class. */}
      <Card className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h2 className="text-h3">{t('declareTitle')}</h2>
          <p className="text-body-s text-ink-500">{t('declareHelp')}</p>
        </div>
        {undeclared.length === 0 ? (
          <p className="text-body-s text-ink-700">{t('allDeclared')}</p>
        ) : (
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex w-full flex-col gap-1.5 sm:w-auto sm:flex-1">
              <span className="text-body-s font-semibold text-ink-700">{ttree('branch')}</span>
              <SelectSurface
                className="rounded-md"
                label={ttree('branch')}
                value={toDeclare || (undeclared[0]?.id ?? '')}
                onChange={(value) => setToDeclare(value as Uuid)}
                options={undeclared.map((s) => ({ value: s.id, label: label(s) }))}
              >
                <span className="flex min-h-11 items-center gap-2 rounded-md border border-line bg-surface px-3">
                  <span className="min-w-0 flex-1 truncate font-semibold text-ink-900">
                    {label(undeclared.find((s) => s.id === (toDeclare || undeclared[0]?.id)))}
                  </span>
                  <IconChevronDown size={16} className="shrink-0 text-ink-500" />
                </span>
              </SelectSurface>
            </div>
            <Button
              variant="primary"
              disabled={declare.isPending}
              onClick={() => {
                const subjectId = (toDeclare || undeclared[0]?.id) as Uuid | undefined;
                if (!subjectId) return;
                setError(null);
                declare.mutate(
                  { classId, subjectId, declare: true },
                  {
                    onError: (caught) => setError(apiErrorMessage(caught, tcode)),
                    onSuccess: () => setToDeclare(''),
                  },
                );
              }}
            >
              {t('declare')}
            </Button>
          </div>
        )}
      </Card>

      <ConfirmDestructive
        open={confirming !== null}
        onOpenChange={(open) => {
          if (!open) {
            setConfirming(null);
            setRemoveError(null);
            setRemoveBlocked(false);
          }
        }}
        title={t('confirmRemoveTitle', { branch: label(confirmingSubject) })}
        description={t('confirmRemoveBody', { code: klass.data?.code ?? '' })}
        alternative={
          <div className="ard-panel flex flex-col gap-1">
            <p className="text-body-s font-bold">{t('confirmRemoveAlternativeTitle')}</p>
            <p className="text-body-s text-ink-700">{t('confirmRemoveAlternativeBody')}</p>
          </div>
        }
        cancelLabel={tc('cancel')}
        confirmLabel={t('confirmRemoveAction')}
        closeLabel={tc('close')}
        pending={declare.isPending || removeBlocked}
        error={removeError}
        onConfirm={() => {
          if (!confirming) return;
          setRemoveError(null);
          declare.mutate(
            { classId, subjectId: confirming, declare: false },
            {
              // The refusal stays IN the dialog and the confirm goes cold. Told
              // anywhere else, the teacher would be looking at a dialog that
              // simply did nothing when they pressed the button.
              onError: (caught) => {
                setRemoveError(removalMessage(caught));
                setRemoveBlocked(
                  caught instanceof ApiError && caught.code === 'branch_holds_sheets',
                );
              },
              onSuccess: () => setConfirming(null),
            },
          );
        }}
      />
    </div>
  );
}
