'use client';

import { Button, Card, Field, RosterInput, parseRoster } from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { use, useState } from 'react';

import { Link, useRouter } from '@/i18n/navigation';
import { StudentEditor } from '@/components/StudentEditor';
import { useAddStudents, useClass, useStudents } from '@/lib/api/queries';
import { apiErrorMessage } from '@/lib/api/error-message';
import type { Uuid } from '@/lib/api/types';

/**
 * Paste more pupils into a class that already exists.
 *
 * The zero-roster empty state on the class page pointed at a button that did
 * nothing; this is where it points now. Numbers continue from the first free
 * slot server-side, so re-pasting a list that overlaps is a 409 rather than a
 * silent renumber — student numbers are printed on paper that may already be
 * on the desk.
 */
export default function RosterPage({
  params,
}: {
  params: Promise<{ classId: string }>;
}) {
  const { classId } = use(params);
  const t = useTranslations('classes');
  const tc = useTranslations('common');
  const tcode = useTranslations('errors.code');
  const tstud = useTranslations('students');
  const router = useRouter();

  const klass = useClass(classId);
  const existing = useStudents(classId);
  const addStudents = useAddStudents();

  const [roster, setRoster] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
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

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-1">{t('addStudents')}</h1>
      <p className="mb-6 text-ink-500">{t('title', { code: klass.data?.code ?? '' })}</p>

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

      {/* The roster is also where a teacher fixes a misspelt name or removes a
          pupil who left. Both were unreachable: the paste screen could only
          ever ADD. Editing opens one pupil at a time — a list of live inputs
          invites the wrong row being changed. */}
      {(existing.data ?? []).length > 0 ? (
        <section className="mt-10">
          <h2 className="mb-3 text-h3">{tstud('title')}</h2>
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
                  <span className="min-w-0 flex-1 truncate font-semibold">
                    {student.first_name} {student.last_name}
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
    </div>
  );
}
