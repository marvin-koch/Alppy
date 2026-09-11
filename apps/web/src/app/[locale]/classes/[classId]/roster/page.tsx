'use client';

import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  LoadingState,
  RosterInput,
  parseRoster,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { use, useState } from 'react';

import { Link, useRouter } from '@/i18n/navigation';
import { StudentEditor } from '@/components/StudentEditor';
import { useAddStudents, useClass, useStudents } from '@/lib/api/queries';
import { apiErrorMessage } from '@/lib/api/error-message';
import type { Uuid } from '@/lib/api/types';
import { useDiscretion } from '@/lib/discreet';
import { takeRoster } from '@/lib/roster-handoff';

/**
 * Paste more pupils into a class that already exists.
 *
 * The zero-roster empty state on the class page pointed at a button that did
 * nothing; this is where it points now. Numbers continue from the first free
 * slot server-side, so re-pasting a list that overlaps is a 409 rather than a
 * silent renumber — student numbers are printed on paper that may already be
 * on the desk.
 */
export default function RosterPage({ params }: { params: Promise<{ classId: string }> }) {
  const { classId } = use(params);
  const t = useTranslations('classes');
  const { hideNames } = useDiscretion();
  const tc = useTranslations('common');
  const tcode = useTranslations('errors.code');
  const te = useTranslations('errors.generic');
  const tstud = useTranslations('students');
  const router = useRouter();

  const klass = useClass(classId);
  const existing = useStudents(classId);
  const addStudents = useAddStudents();

  // Pre-filled when the create-class screen got the class in but not the roster
  // (G16). Read in the initialiser rather than an effect, so the textarea is
  // never briefly empty and nothing overwrites what the teacher has started
  // typing. `takeRoster` clears it, so a reload does not resurrect a list already
  // dealt with.
  const [roster, setRoster] = useState(() => takeRoster(classId) ?? '');
  /** True when this screen was reached by that handoff, so it can say why. */
  const [handedOff] = useState(() => roster !== '');
  const [editing, setEditing] = useState<string | null>(null);
  const [oneFirst, setOneFirst] = useState('');
  const [oneLast, setOneLast] = useState('');
  const [error, setError] = useState<string | null>(null);
  const parsed = parseRoster(roster);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (parsed.length === 0) return;
    try {
      await addStudents.mutateAsync({
        classId,
        body: {
          students: parsed.map((s) => ({ first_name: s.firstName, last_name: s.lastName })),
        },
      });
      router.push(`/classes/${classId}`);
    } catch (cause) {
      setError(apiErrorMessage(cause, tcode));
    }
  }

  // The three branches every sibling screen already ships (F22). This one had
  // none: a slow roster rendered "0 élèves" over an empty list, and a failed
  // one rendered the same thing — so "this class has nobody in it" and "we
  // could not find out" looked identical on the screen whose whole job is to
  // tell you who is in the class.
  if (klass.isLoading || existing.isLoading) {
    return <LoadingState shape="list" label={tc('loading')} rows={5} />;
  }
  if (klass.isError || existing.isError) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={
          <Button
            onClick={() => {
              void klass.refetch();
              void existing.refetch();
            }}
          >
            {tc('retry')}
          </Button>
        }
      />
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-1">{tstud('heading', { code: klass.data?.code ?? '' })}</h1>
      <p className="mb-2 text-ink-500">{tstud('count', { count: existing.data?.length ?? 0 })}</p>

      {/* Arrived here because the class was created and the roster post was not
          (G16). Said plainly: the class exists, nothing was lost, and the list is
          already in the box below waiting to be sent again. Without this the
          teacher lands on an unfamiliar screen with their names mysteriously
          pre-filled and no idea which half succeeded. */}
      {handedOff ? (
        <p className="mb-6 rounded-sm bg-warn-100 p-3 text-body-s text-warn-700" role="status">
          {tstud('rosterHandoff')}
        </p>
      ) : (
        <div className="mb-6" />
      )}

      {/* The roster is also where a teacher fixes a misspelt name or removes a
          pupil who left. Both were unreachable: the paste screen could only
          ever ADD. Editing opens one pupil at a time — a list of live inputs
          invites the wrong row being changed. */}
      {(existing.data ?? []).length === 0 ? (
        <EmptyState
          className="mt-6"
          size="sm"
          title={tstud('empty.title')}
          description={tstud('empty.body')}
        />
      ) : null}

      {(existing.data ?? []).length > 0 ? (
        <section className="mt-10">
          <ul className="flex flex-col gap-2">
            {(existing.data ?? []).map((student) =>
              editing === student.id ? (
                <li key={student.id}>
                  <StudentEditor
                    student={student}
                    classId={classId as Uuid}
                    onDone={() => setEditing(null)}
                  />
                </li>
              ) : (
                <li
                  key={student.id}
                  className="flex min-h-11 items-center gap-4 rounded-md border border-line bg-surface px-4 py-2"
                >
                  <span className="w-20 shrink-0 font-mono text-label text-ink-500">
                    {student.uid}
                  </span>
                  {/* The UID column to the left is always there, so in
                      projector mode this becomes an em dash rather than a
                      second copy of it. */}
                  <span className="min-w-0 flex-1 truncate font-semibold">
                    {hideNames ? '—' : `${student.first_name} ${student.last_name}`}
                  </span>
                  <Button variant="ghost" onClick={() => setEditing(student.id)}>
                    {tstud('edit')}
                  </Button>
                </li>
              ),
            )}
          </ul>
        </section>
      ) : null}

      {/* One pupil, without pasting a list. Not a second write path: it posts
          the same roster route with a single entry, because the uid/number
          arithmetic is the one piece of arithmetic here that gets printed on
          paper and must have exactly one implementation (D76). */}
      <section className="mt-10">
        <h2 className="mb-1 text-h3">{tstud('addOne')}</h2>
        <p className="mb-3 text-body-s text-ink-500">{tstud('addOneHelp')}</p>
        <div className="flex flex-wrap items-end gap-3">
          <Field label={tstud('firstName')} className="min-w-[10rem] flex-1">
            <Input value={oneFirst} onChange={(e) => setOneFirst(e.target.value)} />
          </Field>
          <Field label={tstud('lastName')} className="min-w-[10rem] flex-1">
            <Input value={oneLast} onChange={(e) => setOneLast(e.target.value)} />
          </Field>
          <Button
            variant="secondary"
            disabled={addStudents.isPending || !oneFirst.trim() || !oneLast.trim()}
            onClick={() => {
              setError(null);
              addStudents.mutate(
                {
                  classId: classId as Uuid,
                  body: { students: [{ first_name: oneFirst, last_name: oneLast }] },
                },
                {
                  onSuccess: () => {
                    setOneFirst('');
                    setOneLast('');
                  },
                  onError: (caught) => setError(apiErrorMessage(caught, tcode)),
                },
              );
            }}
          >
            {tstud('addOne')}
          </Button>
        </div>
      </section>

      <h2 className="mb-3 mt-10 text-h3">{t('addStudents')}</h2>
      <form onSubmit={submit} noValidate>
        <Card className="mb-4">
          <Field label={t('addStudents')} help={t('rosterHelp')} hideLabel>
            <RosterInput
              value={roster}
              onValueChange={setRoster}
              rows={10}
              renderSummary={(count) => t('rosterPreview', { count })}
            />
          </Field>
          {(existing.data ?? []).length > 0 ? (
            <p className="mt-3 text-body-s text-ink-500">
              {t('rosterAdded', { count: existing.data?.length ?? 0 })}
            </p>
          ) : null}
        </Card>

        {error ? (
          <p role="alert" className="mb-4 text-body-s text-danger-600">
            {error}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="submit"
            variant="primary"
            disabled={addStudents.isPending || parsed.length === 0}
          >
            {addStudents.isPending ? tc('loading') : t('save')}
          </Button>
          <Link href={`/classes/${classId}`}>{t('cancel')}</Link>
        </div>
      </form>
    </div>
  );
}
